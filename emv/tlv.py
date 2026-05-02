"""
BER-TLV (Basic Encoding Rules - Tag Length Value) parser and encoder
used for EMV data elements.
"""

from emv.data_elements import EMV_TAGS


class TLVError(Exception):
    pass


class TLV:
    def __init__(self, tag, value, children=None):
        self.tag = tag
        self.value = value
        self.children = children or []

    @property
    def tag_hex(self):
        if self.tag <= 0xFF:
            return "{:02X}".format(self.tag)
        elif self.tag <= 0xFFFF:
            return "{:04X}".format(self.tag)
        else:
            return "{:06X}".format(self.tag)

    @property
    def value_hex(self):
        return self.value.hex().upper()

    @property
    def name(self):
        info = EMV_TAGS.get(self.tag, {})
        return info.get("name", "Unknown Tag 0x{:X}".format(self.tag))

    @property
    def is_constructed(self):
        if self.tag <= 0xFF:
            return bool(self.tag & 0x20)
        first_byte = (self.tag >> ((len("{:X}".format(self.tag)) // 2) * 4)) & 0xFF
        return bool(first_byte & 0x20)

    def __repr__(self):
        if self.is_constructed:
            return "TLV(tag=0x{:X} [{}], children={})".format(
                self.tag, self.name, self.children)
        return "TLV(tag=0x{:X} [{}], value={})".format(
            self.tag, self.name, self.value_hex)

    def to_dict(self):
        result = {
            "tag": self.tag_hex,
            "name": self.name,
            "length": len(self.value),
        }
        if self.is_constructed and self.children:
            result["children"] = [c.to_dict() for c in self.children]
        else:
            result["value"] = self.value_hex
        return result


def _parse_tag(data, offset):
    if offset >= len(data):
        raise TLVError("Unexpected end of data while parsing tag")

    first_byte = data[offset]
    offset += 1

    if (first_byte & 0x1F) == 0x1F:
        tag = first_byte
        while offset < len(data):
            b = data[offset]
            offset += 1
            tag = (tag << 8) | b
            if not (b & 0x80):
                break
        else:
            raise TLVError("Unexpected end of data in multi-byte tag")
    else:
        tag = first_byte

    return tag, offset


def _parse_length(data, offset):
    if offset >= len(data):
        raise TLVError("Unexpected end of data while parsing length")

    first_byte = data[offset]
    offset += 1

    if first_byte == 0x80:
        raise TLVError("Indefinite length form not supported")
    elif first_byte & 0x80:
        num_bytes = first_byte & 0x7F
        if offset + num_bytes > len(data):
            raise TLVError("Unexpected end of data in multi-byte length")
        length = 0
        for i in range(num_bytes):
            length = (length << 8) | data[offset + i]
        offset += num_bytes
    else:
        length = first_byte

    return length, offset


def parse(data):
    if isinstance(data, str):
        data = bytes.fromhex(data)

    results = []
    offset = 0

    while offset < len(data):
        if data[offset] == 0x00 or data[offset] == 0xFF:
            offset += 1
            continue

        tag, offset = _parse_tag(data, offset)
        length, offset = _parse_length(data, offset)

        if offset + length > len(data):
            raise TLVError(
                "Value length {} exceeds available data at offset {}".format(
                    length, offset))

        value = data[offset:offset + length]
        offset += length

        tlv = TLV(tag, value)

        if tlv.is_constructed:
            try:
                tlv.children = parse(value)
            except TLVError:
                pass

        results.append(tlv)

    return results


def parse_one(data):
    results = parse(data)
    if not results:
        raise TLVError("No TLV found in data")
    return results[0]


def find_tag(tlv_list, tag):
    for tlv in tlv_list:
        if tlv.tag == tag:
            return tlv
        if tlv.children:
            result = find_tag(tlv.children, tag)
            if result:
                return result
    return None


def find_all_tags(tlv_list, tag):
    results = []
    for tlv in tlv_list:
        if tlv.tag == tag:
            results.append(tlv)
        if tlv.children:
            results.extend(find_all_tags(tlv.children, tag))
    return results


def encode_tag(tag):
    if tag <= 0xFF:
        return bytes([tag])
    elif tag <= 0xFFFF:
        return bytes([(tag >> 8) & 0xFF, tag & 0xFF])
    elif tag <= 0xFFFFFF:
        return bytes([(tag >> 16) & 0xFF, (tag >> 8) & 0xFF, tag & 0xFF])
    else:
        return bytes([(tag >> 24) & 0xFF, (tag >> 16) & 0xFF,
                      (tag >> 8) & 0xFF, tag & 0xFF])


def encode_length(length):
    if length <= 0x7F:
        return bytes([length])
    elif length <= 0xFF:
        return bytes([0x81, length])
    elif length <= 0xFFFF:
        return bytes([0x82, (length >> 8) & 0xFF, length & 0xFF])
    else:
        raise TLVError("Length {} too large to encode".format(length))


def encode(tag, value):
    if isinstance(value, str):
        value = bytes.fromhex(value)
    return encode_tag(tag) + encode_length(len(value)) + value


def encode_constructed(tag, children):
    inner = b""
    for child_tag, child_value in children:
        inner += encode(child_tag, child_value)
    return encode(tag, inner)


def tlv_list_to_hex(tlv_list):
    result = b""
    for tlv in tlv_list:
        result += encode_tag(tlv.tag) + encode_length(len(tlv.value)) + tlv.value
    return result.hex().upper()


def extract_emv_fields(emv_data_hex):
    try:
        tlv_list = parse(emv_data_hex)
        fields = {}
        _extract_recursive(tlv_list, fields)
        return fields
    except Exception as e:
        return {"error": str(e)}


def _extract_recursive(tlv_list, fields):
    for tlv in tlv_list:
        tag_hex = tlv.tag_hex
        fields[tag_hex] = {
            "name": tlv.name,
            "value": tlv.value_hex,
            "length": len(tlv.value),
        }
        if tlv.children:
            _extract_recursive(tlv.children, fields)
