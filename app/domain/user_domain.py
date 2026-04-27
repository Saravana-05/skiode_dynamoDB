class LoginRequest:

    def __init__(self, username: str, password: str):
        if not username:
            raise ValueError("username is required")
        if not password:
            raise ValueError("password is required")

        self.username = username
        self.password = password


class UserData:

    def __init__(
        self,
        user_name=None,
        mail_id=None,
        profile_pic=None,
        organization_id=None,
        usergroup_id=None,
        is_lead=None,
        ref_id=None
    ):
        self.user_name = user_name
        self.mail_id = mail_id
        self.profile_pic = profile_pic
        self.organization_id = organization_id
        self.usergroup_id = usergroup_id
        self.is_lead = is_lead
        self.ref_id = ref_id


class User:

    def __init__(
        self,
        id: int,
        username: str,
        email: str,
        is_active: bool,
        user_data: UserData = None
    ):
        self.id = id
        self.username = username
        self.email = email
        self.is_active = is_active
        self.user_data = user_data
