def parse_flags(argv):
    return {
        "verbose": "--debug" in argv,
        "limit": 10,
    }
