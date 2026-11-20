"""MySQL schema and account-scoped persistence for Piano AI Coach."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from hmac import compare_digest
from secrets import token_urlsafe

import pymysql
from cryptography.fernet import Fernet
from pymysql.cursors import DictCursor


class WorkspaceDB:
    def __init__(self):
        self.options = {
            "host": os.environ.get("PIANO_DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("PIANO_DB_PORT", 3306)),
            "user": os.environ.get("PIANO_DB_USER", "piano"),
            "password": os.environ.get("PIANO_DB_PASSWORD", ""),
            "database": os.environ.get("PIANO_DB_NAME", "piano"),
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "connect_timeout": 5,
            "read_timeout": 10,
            "write_timeout": 10,
        }
        secret = os.environ["PIANO_SECRET_KEY"]
        self.cipher = Fernet(secret.encode())
        with self.connect() as db:
            for statement in SCHEMA:
                db.execute(statement + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")

    @contextmanager
    def connect(self):
        connection = pymysql.connect(**self.options)
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()

    def create_user(self, username, password, role="user"):
        salt = os.urandom(16).hex()
        stored = salt + ":" + self.password_hash(password, salt)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO users (username,password_hash,role) VALUES (%s,%s,%s)",
                           (username, stored, role))
                return {"id": db.lastrowid, "username": username, "role": role}
        except pymysql.err.IntegrityError:
            raise ValueError("此账号已被使用") from None

    def authenticate(self, username, password):
        with self.connect() as db:
            db.execute("SELECT * FROM users WHERE username=%s", (username,))
            row = db.fetchone()
        salt, expected = row["password_hash"].split(":") if row else ("0" * 32, "0" * 64)
        if not compare_digest(self.password_hash(password, salt), expected) or row is None:
            return None
        return {key: row[key] for key in ("id", "username", "role")}

    def admin(self):
        with self.connect() as db:
            db.execute("SELECT id,username,role FROM users WHERE role='admin' LIMIT 1")
            return db.fetchone()

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(self, user_id, max_age):
        token = token_urlsafe(32)
        now = int(time.time())
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=%s", (now,))
            db.execute("INSERT INTO sessions VALUES (%s,%s,%s)", (self.token_hash(token), user_id, now + max_age))
        return token

    def session(self, token):
        with self.connect() as db:
            db.execute("""
                SELECT users.id,users.username,users.role FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE token_hash=%s AND expires_at>%s
            """, (self.token_hash(token), int(time.time())))
            return db.fetchone()

    def end_session(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=%s", (self.token_hash(token),))

    def attach_resource(self, resource_id, owner_id, kind, library=None):
        with self.connect() as db:
            db.execute("INSERT INTO resources VALUES (%s,%s,%s)", (resource_id, owner_id, kind))
            if library:
                db.execute("INSERT INTO midi_library VALUES (%s,%s,%s,%s)",
                           (resource_id, owner_id, library["created_at"], json.dumps(library, ensure_ascii=False)))

    def resources(self, owner_id, kind):
        with self.connect() as db:
            db.execute("SELECT resource_id FROM resources WHERE owner_id=%s AND kind=%s", (owner_id, kind))
            return [row["resource_id"] for row in db.fetchall()]

    def owns(self, owner_id, resource_id):
        with self.connect() as db:
            db.execute("SELECT 1 FROM resources WHERE resource_id=%s AND owner_id=%s", (resource_id, owner_id))
            return bool(db.fetchone())

    def import_legacy_resources(self, resources, owner_id):
        if resources:
            with self.connect() as db:
                db.executemany("INSERT IGNORE INTO resources VALUES (%s,%s,%s)",
                               [(item, owner_id, kind) for item, kind in resources])

    def coach_config(self, decrypt=False):
        with self.connect() as db:
            db.execute("SELECT endpoint,model,api_key FROM coach_config WHERE singleton=1")
            result = db.fetchone()
        if result and decrypt and result["api_key"]:
            result["api_key"] = self.cipher.decrypt(result["api_key"].encode()).decode()
        return result

    def set_coach_config(self, endpoint, model, api_key):
        secret = self.cipher.encrypt(api_key.encode()).decode() if api_key else api_key
        with self.connect() as db:
            db.execute("""
                INSERT INTO coach_config VALUES (1,%s,%s,COALESCE(%s,''))
                ON DUPLICATE KEY UPDATE endpoint=%s,model=%s,api_key=COALESCE(%s,api_key)
            """, (endpoint, model, secret, endpoint, model, secret))

    def disable_coach(self):
        with self.connect() as db:
            db.execute("DELETE FROM coach_config WHERE singleton=1")

    def add_message(self, owner_id, job_id, message):
        with self.connect() as db:
            db.execute("INSERT INTO coach_messages VALUES (%s,%s,%s,%s,%s)",
                       (message["id"], owner_id, job_id, message["created_at"], json.dumps(message, ensure_ascii=False)))

    def messages(self, owner_id, job_id):
        with self.connect() as db:
            db.execute("SELECT payload FROM coach_messages WHERE owner_id=%s AND job_id=%s ORDER BY created_at",
                       (owner_id, job_id))
            return [json.loads(row["payload"]) for row in db.fetchall()]

    def library(self, owner_id):
        with self.connect() as db:
            db.execute("SELECT payload FROM midi_library WHERE owner_id=%s ORDER BY created_at DESC", (owner_id,))
            return [json.loads(row["payload"]) for row in db.fetchall()]

    def practice(self, owner_id):
        with self.connect() as db:
            db.execute("SELECT * FROM practice WHERE owner_id=%s ORDER BY created_at DESC", (owner_id,))
            return db.fetchall()

    def add_practice(self, task):
        with self.connect() as db:
            db.execute("""
                INSERT INTO practice (id,owner_id,title,detail,job_id,start_seconds,end_seconds,created_at)
                VALUES (%(id)s,%(owner_id)s,%(title)s,%(detail)s,%(job_id)s,%(start_seconds)s,%(end_seconds)s,%(created_at)s)
            """, task)
            return {**task, "completed_at": None}

    def change_practice(self, owner_id, task_id, action, values):
        with self.connect() as db:
            identity = (task_id, owner_id)
            db.execute("SELECT id FROM practice WHERE id=%s AND owner_id=%s FOR UPDATE", identity)
            if db.fetchone() is None:
                raise ValueError("练习项目不存在")
            if action == "remove":
                db.execute("DELETE FROM practice WHERE id=%s AND owner_id=%s", identity)
                return {"removed": True}
            if action == "edit":
                db.execute("UPDATE practice SET title=%s,detail=%s WHERE id=%s AND owner_id=%s", (*values, *identity))
            else:
                db.execute("UPDATE practice SET completed_at=%s WHERE id=%s AND owner_id=%s", (*values, *identity))
            db.execute("SELECT * FROM practice WHERE id=%s AND owner_id=%s", identity)
            return db.fetchone()


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, username VARCHAR(32) UNIQUE NOT NULL,
        password_hash CHAR(97) NOT NULL, role ENUM('user','admin') NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash CHAR(64) PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL, expires_at BIGINT UNSIGNED NOT NULL,
        INDEX (expires_at), FOREIGN KEY (user_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS resources (
        resource_id CHAR(32) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, kind ENUM('asset','job') NOT NULL,
        INDEX (owner_id, kind), FOREIGN KEY (owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS coach_config (
        singleton TINYINT UNSIGNED PRIMARY KEY CHECK (singleton=1),
        endpoint VARCHAR(2000) NOT NULL, model VARCHAR(200) NOT NULL, api_key TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS coach_messages (
        id CHAR(32) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, job_id CHAR(32) NOT NULL,
        created_at VARCHAR(40) NOT NULL, payload JSON NOT NULL,
        INDEX (owner_id, job_id, created_at), FOREIGN KEY (owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS practice (
        id CHAR(32) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, title VARCHAR(120) NOT NULL,
        detail TEXT NOT NULL, job_id CHAR(32) NOT NULL, start_seconds DOUBLE, end_seconds DOUBLE,
        created_at VARCHAR(40) NOT NULL, completed_at VARCHAR(40),
        INDEX (owner_id, created_at), FOREIGN KEY (owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS midi_library (
        asset_id CHAR(32) PRIMARY KEY, owner_id BIGINT UNSIGNED NOT NULL, created_at VARCHAR(40) NOT NULL,
        payload JSON NOT NULL, INDEX (owner_id, created_at), FOREIGN KEY (owner_id) REFERENCES users(id),
        FOREIGN KEY (asset_id) REFERENCES resources(resource_id)
    )""",
)
