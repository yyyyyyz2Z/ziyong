import re

from .errors import InvalidCredentials


SESSION_AGE = 7 * 24 * 60 * 60


def credentials(data):
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", username.strip()):
        raise ValueError("用户名须为 3–32 位字母、数字、下划线或短横线")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("密码长度须为 8–128 个字符")
    return username.strip().lower(), password


class AccountService:
    def __init__(self, database, admin_username):
        self.database = database
        self.admin_username = admin_username

    def bootstrap_admin(self, password):
        admin = self.database.admin()
        if not admin and password:
            username, password = credentials({"username": self.admin_username, "password": password})
            admin = self.database.create_user(username, password, "admin")
        return admin

    def start_session(self, data, previous, *, register):
        username, password = credentials(data)
        if register:
            if username == self.admin_username:
                raise ValueError("此账号不可注册")
            account = self.database.create_user(username, password)
        else:
            account = self.database.authenticate(username, password)
            if not account:
                raise InvalidCredentials("账号或密码不正确")
        self.logout(previous)
        return account, self.database.create_session(account["id"], SESSION_AGE)

    def account(self, token):
        return self.database.session(token) if token else None

    def logout(self, token):
        if token:
            self.database.end_session(token)
