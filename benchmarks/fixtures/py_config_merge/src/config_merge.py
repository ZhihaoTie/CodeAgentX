def merge_config(defaults, overrides):
    merged = defaults
    merged.update(overrides)
    return merged
