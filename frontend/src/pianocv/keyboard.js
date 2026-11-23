import {bendPoint} from '#pianocv-core';
import {detectFrame} from './detector';

export const frameUrl = (video, time) => '/api/assets/' + video.id + '/frame?time=' + time;

export function sampleTimes(video) {
  const last = Math.max(0, video.duration - 1 / video.fps);
  return [...new Set([Math.min(last, 2), 0, last / 2, last].map(time => Math.floor(time * 1000) / 1000))];
}

function isConvexQuad(corners) {
  const crosses = corners.map(([ax, ay], i) => {
    const [bx, by] = corners[(i + 1) % 4], [cx, cy] = corners[(i + 2) % 4];
    return (bx - ax) * (cy - by) - (by - ay) * (cx - bx);
  });
  return crosses.every(value => value > 0) || crosses.every(value => value < 0);
}

function area(points) {
  return Math.abs(points.reduce((sum, [x, y], index) => {
    const [nextX, nextY] = points[(index + 1) % points.length];
    return sum + x * nextY - y * nextX;
  }, 0)) / 2;
}

export function keyboardCrop(corners, width, height) {
  const x = corners.map(p => p[0]), y = corners.map(p => p[1]);
  const left = Math.min(...x), right = Math.max(...x), top = Math.min(...y), bottom = Math.max(...y);
  if (!isConvexQuad(corners) || right - left < width * .20 || bottom - top < height * .035) {
    throw new Error('请按顺序框选完整键盘的四角，并包括键盘两端。');
  }
  // Keep the source aspect ratio where possible. Tight, very wide crops put
  // the keys at a different scale from the model's normal search frames.
  const marginX = (right - left) * .08;
  const x0 = Math.max(0, left - marginX);
  const cropWidth = Math.min(width, right + marginX) - x0;
  const cropHeight = Math.min(height, Math.max((bottom - top) * 1.6, cropWidth * height / width));
  const y0 = Math.max(0, Math.min(height - cropHeight, (top + bottom - cropHeight) / 2));
  return [x0, y0, cropWidth, cropHeight];
}

export async function locateKeyboard(video, time, mirrored, corners, signal) {
  const bounds = corners ? keyboardCrop(corners, video.width, video.height) : [0, 0, video.width, video.height];
  const [x0, y0, cropWidth, cropHeight] = bounds;
  const response = await fetch(frameUrl(video, time), {signal: AbortSignal.any([signal, AbortSignal.timeout(15000)])});
  if (!response.ok) throw new Error('读取视频画面失败，请重试。');
  const bitmap = await createImageBitmap(await response.blob());
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 1440 / Math.max(cropWidth, cropHeight));
  canvas.width = Math.max(1, Math.round(cropWidth * scale));
  canvas.height = Math.max(1, Math.round(cropHeight * scale));
  const context = canvas.getContext('2d');
  try {
    if (mirrored) {
      context.translate(canvas.width, 0);
      context.scale(-1, 1);
    }
    context.drawImage(bitmap, x0, y0, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
  } finally {
    bitmap.close();
  }
  const {width, height} = canvas;
  const {keys, fit} = await detectFrame(canvas, {width, height}, () => signal.throwIfAborted());
  if (fit?.phase !== 'A' || fit.whiteKeys !== 52 || keys.length !== 88 ||
      !keys.every((key, index) => key.semitone === index)) return null;

  const toPixel = ({x, y}) => [x0 + (mirrored ? 1 - x : x) * cropWidth, y0 + y * cropHeight];
  const inFrame = ([x, y]) => Number.isFinite(x) && Number.isFinite(y) &&
    x >= 0 && x < video.width && y >= 0 && y < video.height;
  const points = fit.quad.map(p => toPixel(bendPoint(fit.lens, p)));
  if (!points.every(inFrame) || !isConvexQuad(points) || area(points) < 5000 ||
      Math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1]) < 208) return null;
  const outlines = keys.map(key => ({
    midi_pitch: 21 + key.semitone, outline: key.bar.map(toPixel),
    surface: key.top.map(toPixel),
  }));
  if (outlines.some(key => key.surface.length < 3 || ![...key.outline, ...key.surface].every(inFrame) ||
      area(key.outline) < 1 || area(key.surface) < 1)) return null;
  const round = points => points.map(point => point.map(value => Math.floor(value * 100) / 100));
  return {
    source: corners ? 'pianocv_crop' : 'pianocv_auto', time,
    corners: round(mirrored ? [points[1], points[0], points[3], points[2]] : points),
    keys: outlines.map(key => ({...key, outline: round(key.outline), surface: round(key.surface)})),
  };
}
