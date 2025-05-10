"""Client for interacting with JFA-GO API."""

import datetime
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

from modules.config import get_config_value


class JfaGoClient:
    """Client for interacting with JFA-GO API"""

    def __init__(self, base_url: str, username: str, password: str):
        self.logger = logging.getLogger(
            self.__class__.__name__
        )  # Logger for JfaGoClient class
        if not all([base_url, username, password]):
            self.logger.critical(
                "Missing required JFA-GO credentials at client initialization."
            )
            raise ValueError("Missing required JFA-GO credentials")

        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.auth_token = None
        self.session = requests.Session()
        self.token_expiry = None
        self._setup_session()
        self._invite_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._profile_cache: Optional[List[str]] = None
        # Cache related timestamps (use None to indicate not cached yet)
        self._invite_cache_expiry: Optional[float] = None
        self._profile_cache_expiry: Optional[float] = None
        self._cache_duration_seconds = 300  # 5 minutes cache duration

    def _setup_session(self) -> None:
        """Setup the session with proper timeouts and retries"""
        try:
            self.logger.debug("Setting up requests session with headers and retries.")
            self.session.headers.update(
                {"User-Agent": "JFA-GO Discord Bot/1.0", "Accept": "application/json"}
            )
            retry_strategy = requests.adapters.Retry(
                total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.logger.info("Requests Session configured with retry strategy.")
        except Exception as e:
            self.logger.error(f"Error setting up requests session: {str(e)}")
            raise

    def _log_api_call(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        response: Optional[requests.Response] = None,
    ) -> None:
        """Log API calls in debug mode"""
        if not get_config_value("bot_settings.debug_mode", False):
            return

        # Redact sensitive info if necessary (e.g., password in payload for login)
        safe_payload = payload
        if "/token/login" in url and payload:
            safe_payload = payload.copy()
            if "password" in safe_payload:
                safe_payload["password"] = "***REDACTED***"

        log_data = {
            "method": method,
            "url": url,
            "payload": safe_payload,  # Log potentially redacted payload
            "status_code": response.status_code if response else None,
            "response_headers": dict(response.headers) if response else None,
            "response_body": None,
        }

        # Attempt to parse JSON response, fall back to text
        if response is not None:
            try:
                if (
                    response.text
                    and response.headers.get("content-type") == "application/json"
                ):
                    log_data["response_body"] = response.json()
                else:
                    log_data["response_body"] = response.text[
                        :1000
                    ]  # Limit text response log size
            except json.JSONDecodeError:
                log_data["response_body"] = (
                    f"(Non-JSON Response, starts with: {response.text[:200]}...)"
                )

        self.logger.debug(
            f"JFA-GO API Call: {json.dumps(log_data, indent=2, default=str)}"
        )

    def login(self) -> bool:
        """Authenticate and get the auth token"""
        try:
            self.logger.info("Attempting JFA-GO login...")
            response = self.session.get(
                f"{self.base_url}/token/login",
                auth=(self.username, self.password),
                timeout=10,
            )

            # Log the call - _log_api_call won't see the auth tuple directly
            self._log_api_call("GET", f"{self.base_url}/token/login", response=response)

            if response.status_code == 200:
                try:
                    response_json = response.json()
                    # Avoid logging the raw token itself even in debug if possible
                    self.logger.debug("Login successful, received token data.")

                    # Check for token in response
                    if "token" in response_json:
                        self.auth_token = response_json["token"]
                        # Calculate expiry with a buffer
                        expires_seconds = response_json.get(
                            "expires", 3300
                        )  # 55 minutes in seconds
                        expiry_buffer_seconds = 60
                        self.token_expiry = (
                            datetime.datetime.now()
                            + datetime.timedelta(
                                seconds=max(0, expires_seconds - expiry_buffer_seconds)
                            )
                        )
                        self.logger.info(
                            f"Successfully obtained JFA-GO auth token, expires approx {self.token_expiry.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        return True
                    else:
                        self.logger.error(
                            f"JFA-GO Login response successful (200) but 'token' key missing in JSON: {response_json}"
                        )
                        return False
                except json.JSONDecodeError as e:
                    self.logger.error(
                        f"Failed to parse JSON from successful JFA-GO login response: {str(e)}"
                    )
                    self.logger.debug(f"Raw login response text: {response.text}")
                    return False
            elif response.status_code == 401:
                self.logger.error(
                    "JFA-GO Login failed: Invalid credentials (401 Unauthorized)"
                )
                return False
            else:
                self.logger.error(
                    f"JFA-GO Login failed with status {response.status_code}"
                )
                self.logger.debug(f"Raw login failure response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error during JFA-GO login: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error during JFA-GO login: {str(e)}", exc_info=True
            )
            return False

    def ensure_auth(self) -> bool:
        """Ensure we have a valid auth token, attempting login if needed."""
        self.logger.debug("Checking JFA-GO authentication status...")
        try:
            if not self.auth_token:
                self.logger.info("No JFA-GO auth token present. Attempting login.")
                return self.login()
            elif self.token_expiry and datetime.datetime.now() >= self.token_expiry:
                self.logger.info(
                    f"JFA-GO auth token expired (Expiry was {self.token_expiry.strftime('%Y-%m-%d %H:%M:%S')}). Attempting re-login."
                )
                return self.login()
            else:
                self.logger.debug(
                    f"JFA-GO auth token is valid (Expires approx {self.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if self.token_expiry else 'N/A'})."
                )
                return True
        except Exception as e:
            self.logger.error(
                f"Error ensuring JFA-GO authentication: {str(e)}", exc_info=True
            )
            return False

    def get_profiles(self) -> Tuple[Optional[List[str]], str]:
        """Get the available user profiles from JFA-GO"""
        now = datetime.datetime.now().timestamp()
        if not self.ensure_auth():
            return None, "Authentication failed"

        # Check cache first
        if (
            self._profile_cache is not None
            and self._profile_cache_expiry is not None
            and now < self._profile_cache_expiry
        ):
            self.logger.debug("Returning JFA-GO profiles from cache.")
            return self._profile_cache, "Found profiles in cache"

        try:
            self.logger.info("Fetching profiles from JFA-GO API...")
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            response = self.session.get(
                f"{self.base_url}/profiles", headers=headers, timeout=15
            )

            self._log_api_call("GET", f"{self.base_url}/profiles", response=response)

            if response.status_code == 401:
                self.logger.warning(
                    "Got 401 fetching JFA-GO profiles, attempting token refresh"
                )
                # Clear potentially invalid token before retrying
                self.auth_token = None
                self.token_expiry = None
                if self.login():
                    return self.get_profiles()
                return None, "Authentication failed when refreshing token"

            if response.status_code == 200:
                try:
                    data = response.json()
                    profiles_dict = data.get("profiles")
                    if isinstance(profiles_dict, dict):
                        profile_names = list(profiles_dict.keys())
                        self.logger.debug(
                            f"Successfully parsed {len(profile_names)} profile names from JFA-GO API."
                        )
                    else:
                        self.logger.error(
                            f"Unexpected structure for 'profiles' key in JFA-GO response: {type(profiles_dict)}"
                        )
                        self.logger.debug(f"Raw profiles response: {response.text}")
                        return (
                            None,
                            "Unexpected response structure from JFA-GO profiles endpoint",
                        )

                    if profile_names:
                        self._profile_cache = profile_names
                        self._profile_cache_expiry = now + self._cache_duration_seconds
                        self.logger.info(
                            f"Successfully fetched and cached {len(profile_names)} JFA-GO profiles. Cache valid until approx {datetime.datetime.fromtimestamp(self._profile_cache_expiry).strftime('%H:%M:%S')}."
                        )
                        return profile_names, "Successfully fetched profiles"
                    else:
                        self.logger.warning(
                            "JFA-GO profiles API returned success but no profile names found in the 'profiles' object."
                        )
                        # Cache the empty result to avoid repeated calls for a short time
                        self._profile_cache = []
                        self._profile_cache_expiry = now + self._cache_duration_seconds
                        return [], "No profiles found"
                except json.JSONDecodeError as e:
                    error_msg = (
                        f"Failed to parse JSON from JFA-GO profiles response: {str(e)}"
                    )
                    self.logger.error(error_msg)
                    return None, error_msg
                except Exception as e:  # Catch broader exceptions during parsing
                    error_msg = f"Error processing JFA-GO profiles response: {str(e)}"
                    self.logger.error(error_msg, exc_info=True)
                    return None, error_msg
            else:
                error_msg = f"Get JFA-GO profiles failed: {response.status_code} - {response.text}"
                self.logger.error(error_msg)
                return None, error_msg

        except requests.exceptions.RequestException as e:
            error_msg = f"Network error getting JFA-GO profiles: {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error getting JFA-GO profiles: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return None, error_msg

    def extend_user_expiry(
        self,
        jfa_username: str,
        months: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        reason: Optional[str] = None,
        notify: bool = True,
        exact_timestamp: Optional[int] = None,  # Optional exact expiry timestamp
    ) -> Tuple[bool, str]:
        """Extend expiry for a JFA-GO user or set an exact expiry timestamp."""
        if not self.ensure_auth():
            return False, "Authentication failed"

        # JFA-GO User ID usually matches username, pass it in the required format
        users_list = [jfa_username]

        payload: Dict[str, Any] = {
            "users": users_list,
            "notify": notify,
        }

        # Prioritize exact timestamp if provided
        if exact_timestamp is not None:
            payload["timestamp"] = exact_timestamp
            self.logger.info(
                f"Setting exact expiry for user(s) {users_list} to timestamp {exact_timestamp}."
            )
        else:
            # Check if at least one duration field is positive
            if not any(d > 0 for d in [months, days, hours, minutes]):
                return False, "No positive duration provided for extension."

            payload["months"] = months
            payload["days"] = days
            payload["hours"] = hours
            payload["minutes"] = minutes
            self.logger.info(
                f"Extending expiry for user(s) {users_list} by M={months}, D={days}, h={hours}, m={minutes}."
            )

        if reason:
            payload["reason"] = reason

        try:
            self.logger.debug(f"Calling JFA-GO /users/extend endpoint for {users_list}")
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
            }
            response = self.session.post(
                f"{self.base_url}/users/extend",
                headers=headers,
                json=payload,
                timeout=20,  # Allow a bit more time for potential backend processing
            )

            self._log_api_call(
                "POST",
                f"{self.base_url}/users/extend",
                payload=payload,
                response=response,
            )

            if response.status_code == 401:
                self.logger.warning(
                    "Got 401 calling JFA-GO /users/extend, attempting token refresh"
                )
                self.auth_token = None
                self.token_expiry = None
                if self.login():
                    return self.extend_user_expiry(  # Retry the call
                        jfa_username,
                        months,
                        days,
                        hours,
                        minutes,
                        reason,
                        notify,
                        exact_timestamp,
                    )
                return False, "Authentication failed when refreshing token"

            # Treat both 200 OK and 204 No Content as success
            if response.status_code in [200, 204]:
                success_msg = f"User expiry action successful for {users_list} (Status: {response.status_code})."
                self.logger.info(success_msg)
                # Return a consistent success message to the command handler
                return True, "User expiry extended successfully."
            elif response.status_code == 400:
                error_msg = f"Bad Request (400) extending expiry: {response.text[:500]}"
                self.logger.error(error_msg)
                return (
                    False,
                    f"Failed to extend expiry: {response.text[:200]} (Check JFA-GO logs for details)",
                )
            elif response.status_code == 404:
                error_msg = f"User Not Found (404) extending expiry for {jfa_username}: {response.text[:500]}"
                self.logger.error(error_msg)
                return False, f"User '{jfa_username}' not found in JFA-GO."
            else:
                self.logger.error(
                    f"Failed to extend user expiry with status {response.status_code}"
                )
                self.logger.debug(
                    f"Raw extend expiry failure response: {response.text}"
                )
                return (
                    False,
                    f"Failed to extend expiry (Status: {response.status_code})",
                )

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout extending JFA-GO user expiry for {users_list}.")
            return False, "Request timed out."
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error extending JFA-GO user expiry: {str(e)}")
            return False, "Network error during extension."
        except Exception as e:
            self.logger.error(
                f"Unexpected error extending JFA-GO user expiry: {str(e)}",
                exc_info=True,
            )
            return False, "Unexpected error during extension."

    def create_invite(
        self,
        label: str,
        profile_name: str = "Basic Profile",  # Default profile
        user_duration_days: Optional[int] = None,  # Duration for the created user
        invite_duration_days: int = 1,  # Duration the invite link is valid
        multiple_uses: bool = False,
        remaining_uses: int = 1,
    ) -> Tuple[bool, str]:
        """Create a new invite with specified parameters"""
        if not self.ensure_auth():
            return False, "Failed to authenticate with JFA-GO server"

        try:
            log_details = f"label='{label}', profile='{profile_name}', user_days={user_duration_days}, invite_days={invite_duration_days}, multiple_uses={multiple_uses}, uses={remaining_uses}"
            self.logger.info(f"Attempting to create JFA-GO invite: {log_details}")
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
            }

            # Determine user expiry settings based on user_duration_days
            user_expiry = user_duration_days is not None and user_duration_days > 0
            self.logger.debug(
                f"Calculated user_expiry={user_expiry} based on user_duration_days={user_duration_days}"
            )
            effective_user_days = (
                user_duration_days if user_expiry else 3
            )  # Default to 3 days if not specified
            self.logger.debug(
                f"Setting effective_user_days={effective_user_days} in payload."
            )

            payload = {
                "days": invite_duration_days,
                "label": label,
                "multiple-uses": multiple_uses,
                "no-limit": remaining_uses
                <= 0,  # Set no-limit if remaining uses is 0 or less
                "profile": profile_name,
                "remaining-uses": remaining_uses
                if remaining_uses > 0
                else 1,  # Ensure positive value if not no-limit
                "send-to": "",
                "user-days": effective_user_days,
                "user-expiry": user_expiry,
            }

            self.logger.debug(f"JFA-GO create invite payload: {json.dumps(payload)}")
            response = self.session.post(
                f"{self.base_url}/invites", headers=headers, json=payload, timeout=30
            )

            self._log_api_call("POST", f"{self.base_url}/invites", payload, response)

            if response.status_code == 401:
                self.logger.warning(
                    "Got 401 during JFA-GO invite creation, attempting token refresh"
                )
                # Clear potentially invalid token before retrying
                self.auth_token = None
                self.token_expiry = None
                if self.login():
                    # Retry the original request recursively
                    return self.create_invite(
                        label,
                        profile_name,
                        user_duration_days,
                        invite_duration_days,
                        multiple_uses,
                        remaining_uses,
                    )
                return False, "Authentication failed when refreshing token"

            if response.status_code == 200:
                self.logger.info(
                    f"Successfully created JFA-GO invite for label: {label}"
                )
                # Invalidate invite cache since we added one
                self._invite_cache_expiry = None
                self._invite_cache.clear()
                return True, "Invite created successfully"
            else:
                error_msg = f"JFA-GO Create invite failed for label '{label}': {response.status_code}"
                self.logger.error(error_msg)
                return False, error_msg

        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Network error creating JFA-GO invite for label '{label}': {str(e)}"
            )
            self.logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = (
                f"Unexpected error creating JFA-GO invite for label '{label}': {str(e)}"
            )
            self.logger.error(error_msg, exc_info=True)
            return False, error_msg

    def get_invite_code(self, label: str) -> Tuple[Optional[str], str]:
        """Get the invite code for a specific label, using cache if possible."""
        now = datetime.datetime.now().timestamp()
        if not self.ensure_auth():
            return None, "Authentication failed"

        try:
            # Check cache first
            if self._invite_cache_expiry and now < self._invite_cache_expiry:
                self.logger.debug(f"Checking invite cache for label: {label}")
                cached_invites = self._invite_cache.get(label)
                if cached_invites:
                    for invite in cached_invites:
                        # Ensure label matches exactly, though API filter should handle this
                        if invite.get("label") == label and invite.get("code"):
                            self.logger.info(
                                f"Found invite code for label '{label}' in cache."
                            )
                            return invite.get("code"), "Found invite code in cache"
            else:
                self.logger.debug("Invite cache miss or expired.")

            # If not in cache or cache expired, fetch from API
            self.logger.info(f"Fetching JFA-GO invites with label: {label}")
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            # URL encode the label parameter to handle special characters
            params = {"label": label}
            response = self.session.get(
                f"{self.base_url}/invites", params=params, headers=headers, timeout=30
            )

            self._log_api_call(
                "GET",
                f"{self.base_url}/invites",
                payload=params,
                response=response,  # Pass params to logger
            )

            if response.status_code == 401:
                self.logger.warning(
                    "Got 401 retrieving JFA-GO invites, attempting token refresh"
                )
                # Clear potentially invalid token before retrying
                self.auth_token = None
                self.token_expiry = None
                if self.login():
                    return self.get_invite_code(label)
                return None, "Authentication failed when refreshing token"

            if response.status_code == 200:
                try:
                    data = response.json()
                    invites = data.get("invites", [])
                    self.logger.debug(
                        f"Received {len(invites)} invites from API for label query '{label}'."
                    )

                    # Update cache (even if empty, cache the result)
                    self._invite_cache[label] = invites
                    self._invite_cache_expiry = now + self._cache_duration_seconds
                    self.logger.debug(
                        f"Updated invite cache for label '{label}'. Cache valid until approx {datetime.datetime.fromtimestamp(self._invite_cache_expiry).strftime('%H:%M:%S')}."
                    )

                    for invite in invites:
                        if invite.get("label") == label and invite.get("code"):
                            self.logger.info(
                                f"Found matching invite code for label '{label}' from API response."
                            )
                            return invite.get("code"), "Found invite code"

                    self.logger.warning(
                        f"No invite found with exact label '{label}' in API response, though API call succeeded."
                    )
                    return None, f"No invite found with label: {label}"
                except json.JSONDecodeError as e:
                    error_msg = (
                        f"Failed to parse JSON from JFA-GO invites response: {str(e)}"
                    )
                    self.logger.error(error_msg)
                    return None, error_msg
            else:
                error_msg = f"Get JFA-GO invites failed for label '{label}': {response.status_code}"
                self.logger.error(error_msg)
                return None, error_msg

        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Network error getting JFA-GO invite for label '{label}': {str(e)}"
            )
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = (
                f"Unexpected error getting JFA-GO invite for label '{label}': {str(e)}"
            )
            self.logger.error(error_msg, exc_info=True)
            return None, error_msg

    def delete_jfa_invite(self, invite_code: str) -> Tuple[bool, str]:
        """Delete an invite from JFA-GO by its code."""
        self.logger.info(f"Attempting to delete JFA-GO invite with code: {invite_code}")
        if not self.ensure_auth():
            return False, "Authentication failed"

        url = f"{self.base_url}/invites"
        payload = {"code": invite_code}
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

        try:
            response = self.session.delete(
                url, headers=headers, json=payload, timeout=15
            )
            self._log_api_call("DELETE", url, payload=payload, response=response)

            if response.status_code == 200:
                try:
                    response_json = response.json()
                    if response_json.get("success"):
                        self.logger.info(
                            f"Successfully deleted invite {invite_code} from JFA-GO."
                        )
                        return True, "Invite successfully deleted from JFA-GO."
                    else:
                        error_msg = response_json.get(
                            "error", "Unknown error from JFA-GO"
                        )
                        self.logger.error(
                            f"JFA-GO returned success=false for deleting invite {invite_code}: {error_msg}"
                        )
                        return False, f"JFA-GO failed to delete invite: {error_msg}"
                except json.JSONDecodeError:
                    self.logger.error(
                        f"Failed to parse JSON response from JFA-GO after deleting invite {invite_code}. Status: {response.status_code}, Response: {response.text[:200]}"
                    )
                    # Consider it a success if status is 200 but response is not JSON, as per JFA-GO docs (sometimes it's just "OK")
                    if response.text.strip().lower() == "ok":
                        self.logger.info(
                            f"Successfully deleted invite {invite_code} from JFA-GO (received OK)."
                        )
                        return (
                            True,
                            "Invite successfully deleted from JFA-GO (received OK).",
                        )
                    return False, "Failed to parse JFA-GO response, but status was 200."

            elif response.status_code == 400:
                try:
                    error_json = response.json()
                    error_message = error_json.get("error", "Bad request")
                    self.logger.error(
                        f"Failed to delete invite {invite_code} from JFA-GO (400 Bad Request): {error_message}"
                    )
                    return False, f"JFA-GO Bad Request: {error_message}"
                except json.JSONDecodeError:
                    self.logger.error(
                        f"Failed to parse JSON error from JFA-GO (400 Bad Request) for invite {invite_code}. Response: {response.text[:200]}"
                    )
                    return False, "JFA-GO Bad Request (could not parse error details)."
            elif response.status_code == 401:
                self.logger.warning(
                    f"Got 401 deleting invite {invite_code} from JFA-GO, attempting token refresh"
                )
                self.auth_token = None  # Clear potentially invalid token
                self.token_expiry = None
                if self.login():
                    return self.delete_jfa_invite(invite_code)  # Retry after login
                return False, "Authentication failed when refreshing token"
            else:
                self.logger.error(
                    f"Failed to delete invite {invite_code} from JFA-GO. Status: {response.status_code}, Response: {response.text[:200]}"
                )
                return False, f"JFA-GO API error (Status: {response.status_code})"

        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"Network error while deleting invite {invite_code} from JFA-GO: {str(e)}"
            )
            return False, f"Network error: {str(e)}"
        except Exception as e:
            self.logger.error(
                f"Unexpected error deleting invite {invite_code} from JFA-GO: {str(e)}",
                exc_info=True,
            )
            return False, f"Unexpected error: {str(e)}"

    def get_jfa_user_details_by_username(
        self, username: str
    ) -> Optional[Dict[str, Any]]:
        """Get details for a specific JFA-GO user by their username."""
        if not self.ensure_auth():
            self.logger.error(
                f"Authentication failed attempting to get details for user {username}."
            )
            return None

        try:
            self.logger.info(f"Fetching details for JFA-GO user: {username}")
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            response = self.session.get(
                f"{self.base_url}/users", headers=headers, timeout=15
            )
            self._log_api_call("GET", f"{self.base_url}/users", response=response)

            if response.status_code == 200:
                users_data_wrapper = response.json()
                if isinstance(users_data_wrapper, dict):
                    actual_user_list = users_data_wrapper.get(
                        "users"
                    )  # Expect list under "users" key
                    if isinstance(actual_user_list, list):
                        self.logger.info(
                            "Found a list of users under the key 'users' in the JFA-GO response."
                        )
                        for user_obj in actual_user_list:
                            if isinstance(user_obj, dict):
                                jfa_api_username = user_obj.get(
                                    "name"
                                )  # Username key is "name"
                                if (
                                    jfa_api_username
                                    and jfa_api_username.lower() == username.lower()
                                ):  # Case-insensitive
                                    self.logger.info(
                                        f"Found user {username} (matched as {jfa_api_username}) in nested list under 'users'."
                                    )
                                    return user_obj
                        self.logger.warning(
                            f"User {username} not found in the list under 'users' key (case-insensitive search performed using key 'name')."
                        )
                        return None  # Searched the list under "users", not found
                    else:
                        self.logger.warning(
                            f"JFA-GO /users response was a dictionary, but the key 'users' did not contain a list. Found type: {type(actual_user_list)}."
                        )
                        if get_config_value("bot_settings.debug_mode", False):
                            self.logger.debug(
                                f"Full dict response from /users: {users_data_wrapper}"
                            )
                        return None
                # This case is if /users itself returns a flat list, which seems not to be the case here.
                elif isinstance(users_data_wrapper, list):
                    self.logger.info(
                        "JFA-GO /users endpoint returned a flat list. Iterating..."
                    )
                    for user_obj in users_data_wrapper:
                        if isinstance(user_obj, dict):
                            jfa_api_username = user_obj.get(
                                "name"
                            )  # Username key is "name"
                            if (
                                jfa_api_username
                                and jfa_api_username.lower() == username.lower()
                            ):  # Case-insensitive
                                self.logger.info(
                                    f"Found user {username} (matched as {jfa_api_username}) in flat list."
                                )
                                return user_obj
                    self.logger.warning(
                        f"User {username} not found in JFA-GO flat user list (case-insensitive search performed using key 'name')."
                    )
                    return None
                else:
                    self.logger.warning(
                        f"Unexpected data structure from JFA-GO /users endpoint. Expected dict or list, got {type(users_data_wrapper)}."
                    )
                    if get_config_value("bot_settings.debug_mode", False):
                        self.logger.debug(
                            f"Full response from /users: {users_data_wrapper}"
                        )
                    return None
            elif response.status_code == 404:
                self.logger.warning(
                    f"JFA-GO user {username} not found (404) when trying to fetch details."
                )
                return None
            else:
                self.logger.error(
                    f"Failed to get JFA-GO user details for {username}: {response.status_code} - {response.text}"
                )
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"Network error getting JFA-GO user details for {username}: {str(e)}"
            )
            return None
        except Exception as e:
            self.logger.error(
                f"Unexpected error getting JFA-GO user details for {username}: {str(e)}",
                exc_info=True,
            )
            return None
