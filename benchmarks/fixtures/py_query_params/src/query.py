def build_query(params):
    return "&".join(f"{key}={value}" for key, value in params.items())
