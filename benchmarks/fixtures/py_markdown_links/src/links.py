def extract_links(markdown):
    return [part for part in markdown.split() if part.startswith("http")]
