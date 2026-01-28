from datetime import datetime

from bisheng.knowledge.domain.models.knowledge import MetadataFieldType


# Convert Time String to Timestamp
def time_str_to_timestamp(time_str):
    try:
        return int(time_str)
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y.%m.%d %H:%M:%S")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%f")
        return int(dt.timestamp())
    except:
        pass

    try:
        dt = datetime.strptime(time_str, "%Yyear%mMonth%dHarian %H:%M:%S")
        return int(dt.timestamp())
    except:
        raise ValueError("Unsupported time format")


# metadata Data Format Conversion
def metadata_value_type_convert(value, target_type: MetadataFieldType):
    try:
        if target_type == MetadataFieldType.NUMBER:
            if not value:
                return 0
            return int(value)
        elif target_type == MetadataFieldType.STRING:
            if not value:
                return None
            return str(value)
        elif target_type == MetadataFieldType.TIME:
            if not value:
                return None
            timestamp = time_str_to_timestamp(value)
            return timestamp
        else:
            raise ValueError("Unsupported target type")
    except Exception as e:
        raise ValueError(f"Failed to convert value '{value}' to type '{target_type}': {e}")
