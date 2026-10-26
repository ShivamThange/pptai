"""Native chart names may be cached references or Office-authored literals."""
def native_series_name(series):
    literal = series._element.xpath("./c:tx/c:v")
    return literal[0].text or "" if literal else series.name
