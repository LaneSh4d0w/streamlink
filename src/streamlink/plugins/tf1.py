"""
$description French live TV channels from TF1 Group, including LCI and TF1.
$url tf1.fr
$url tf1info.fr
$url lci.fr
$type live
$region France
"""

import logging
import re
from urllib.parse import urlparse

from streamlink.plugin import Plugin, PluginError, pluginmatcher
from streamlink.plugin.api import useragents, validate
from streamlink.plugin.plugin import pluginargument
from streamlink.stream.hls import HLSStream


log = logging.getLogger(__name__)


@pluginmatcher(re.compile(r"""
    https?://(?:www\.)?
    (?:
        tf1\.fr/(?:
            (?P<live>[\w-]+)/direct/?
            |
            stream/(?P<stream>[\w-]+)
        )
        |
        (?P<lci>tf1info|lci)\.fr/direct/?
    )
""", re.VERBOSE))
@pluginargument(
    "username",
    requires=["password"],
    metavar="USERNAME",
    help="The username used to register with tf1.fr.",
)
@pluginargument(
    "password",
    prompt="Enter tf1.fr account password",
    sensitive=True,
    metavar="PASSWORD",
    help="A tf1.fr account password to use with --tf1-username.",
)

class TF1(Plugin):
    _URL_API = "https://mediainfo.tf1.fr/mediainfocombo/{channel_id}"
    # Necessary for login.
    _TF1_AUTH_URL = "https://compte.tf1.fr/accounts.login"
    _GIGYA_TOKEN_URL = "https://www.tf1.fr/token/gigya/web"
    gigya_api_key = '3_hWgJdARhz_7l1oOp3a8BDLoR9cuWZpUaKG4aqF7gum9_iK3uTZ2VlDBl8ANf8FVk'
    # Necessary to get the correct cookies launched for delivery.
    user_signature = ""
    user_uid = ""
    user_timestamp = ""
    user_token = ""


    def _get_channel(self):
        if self.match["live"]:
            channel = self.match["live"]
            channel_id = f"L_{channel.upper()}"
        elif self.match["lci"]:
            channel = "LCI"
            channel_id = "L_LCI"
        elif self.match["stream"]:
            channel = self.match["stream"]
            channel_id = f"L_FAST_v2l-{channel}"
        else:  # pragma: no cover
            raise PluginError("Invalid channel")

        return channel, channel_id

    def _api_call(self, channel_id):
        return self.session.http.get(
            self._URL_API.format(channel_id=channel_id),
            params={
                "context": "MYTF1",
                "pver": "5015000",
            },
            headers={
                # forces HLS streams
                "User-Agent": useragents.IPHONE,
                "authorization": f"Bearer {self.user_token}",
            },
            schema=validate.Schema(
                validate.parse_json(),
                {
                    "delivery": validate.any(
                        validate.all(
                            {
                                "code": 200,
                                "format": "hls",
                                "url": validate.url(),
                            },
                            validate.union_get("code", "url"),
                        ),
                        validate.all(
                            {
                                "code": int,
                                "error": str,
                            },
                            validate.union_get("code", "error"),
                        ),
                    ),
                },
                validate.get("delivery"),
            ),
        )
    
    def login(self, ptrt_url):
        """
        Create session using Gigya's API for TF1.

        :param ptrt_url: The snapback URL to redirect to after successful authentication
        :type ptrt_url: string
        :return: Whether authentication was successful
        :rtype: bool
        """

        def auth_check(res):
            # If TF1 login is successful, get Gigya token.
            if res.status_code == 200:
                consent_ids = [ "1", "2", "3", "4", "10001", "10003", "10005", "10007", "10013", "10015", "10017", "10019", "10009", "10011", "13002", "13001", "10004", "10014", "10016", "10018", "10020", "10010", "10012", "10006", "10008"],
                self.user_signature = res.json()['userSignature']
                self.user_uid = res.json()['UID']
                self.user_timestamp = int(res.json()['timestamp'])
                token = self.session.http.post(
                    self._GIGYA_TOKEN_URL,
                    data=dict(
                        uid=self.user_uid,
                        signature=self.user_signature,
                        timestamp=self.user_timestamp,
                        consentIds=consent_ids,
                    ),
                    headers={"Referer": self.url},
                    schema=validate.Schema(
                        validate.parse_json(),
                        {
                            "token": validate.text,
                            "refresh_token": validate.text,
                            "ttl": validate.integer,
                            "type": validate.text,
                        },
                    ),
                )
                self.user_token = token['token']
                return True
            else:
                return False

        # make the session request to get the correct cookies
        session_res = self.session.http.get(
            self.session_url,
            params=dict(ptrt=ptrt_url),
        )

        if auth_check(session_res):
            log.debug("Already authenticated, skipping authentication")
            return True

        res = self.session.http.post(
            self.auth_url,
            params=urlparse(session_res.url).query,
            data=dict(
                loginID=self.get_option("username"),
                password=self.get_option("password"),
                APIKey=self.gigya_api_key,
            ),
            headers={"Referer": self.url})

        return auth_check(res)

    def _get_streams(self):
        if not self.get_option("username"):
            log.error(
                "In order to access your content, TF1 requires an account you must login with, using "
                + "--tf1-username and --tf1-password",
            )
            return
        if not self.login(self.url):
            log.error(
                "Could not authenticate, check your username and password.")
            return

        channel, channel_id = self._get_channel()
        log.debug(f"Found channel {channel} ({channel_id})")

        code, data = self._api_call(channel_id)
        if code != 200:
            log.error(data)
            return

        return HLSStream.parse_variant_playlist(self.session, data)


__plugin__ = TF1
