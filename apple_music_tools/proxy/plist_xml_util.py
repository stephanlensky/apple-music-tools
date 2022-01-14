from xml.etree.ElementTree import Element


def get_xml_dict_key(dict_ele: Element, key: str):
    dict_iter = dict_ele.iter()
    found = False
    for e in dict_iter:
        if e.tag == "key" and e.text == key:
            found = True
            break
    if not found:
        raise KeyError(key)
    e = next(dict_iter)
    return e


def get_xml_array_index(array_ele, idx: int):
    for i, e in enumerate(array_ele):
        if i == idx:
            return e
    raise IndexError("Array index out of range")
