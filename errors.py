class WildcardDNSDetected(Exception):
    """Target uses wildcard DNS (e.g *.google.com),
    Hence it will always flag every subdomain as valid
    even the invalid ones.
    """
