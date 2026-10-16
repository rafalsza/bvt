from sys import exit


def load_correct_creds(creds):
    try:

        return creds["prod"]["access_key"], creds["prod"]["secret_key"]

    except TypeError as te:
        message = "Your credentials are formatted incorectly\n"
        message += f"TypeError:Exception:\n\t{str(te)}"
        exit(message)
    except Exception as e:
        message = "oopsies, looks like you did something real bad. Fallback Exception caught...\n"
        message += f"Exception:\n\t{str(e)}"
        exit(message)


def load_discord_creds(creds):
    return creds["discord"]["DISCORD_WEBHOOK"]


def test_api_key(client, api_exception):
    """Checks to see if API keys supplied returns errors

    Args:
        client (class): exchange client class
        api_exception (class): exchange API exception class

    Returns:
        bool | msg: true/false depending on success, and message
    """
    try:
        client.get_account()
        return True, "API key validated successfully"

    except api_exception as e:

        if e.code == "AUTH_ERROR":
            bad_key = "Your API key, secret or passphrase is not correct..."
            ip_b = "If you set an IP whitelist on your keys make sure this IP address is allowed. check ipinfo.io/ip"
            perm = "Make sure the key has spot read/trade permissions on Bitget."

            msg = f"Your API credentials are either incorrect, IP blocked, or missing permissions...\n  most likely: {bad_key}\n  {perm}\n  {ip_b}"

        elif e.code == "TIMESTAMP_SYNC":
            desc = "Your operating system time is not properly synced... Please sync ntp time with 'pool.ntp.org'"
            msg = f"{desc}\nmaybe try this:\n\tsudo ntpdate pool.ntp.org"
        else:
            msg = "Encountered an API Error code that was not caught nicely, please open issue...\n"
            msg += str(e)

        return False, msg

    except Exception as e:
        return False, f"Fallback exception occured:\n{e}"
