def unique_users(users):
    """Return users deduplicated by id."""

    return list({user["id"]: user for user in users}.values())
