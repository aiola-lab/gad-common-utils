from common_utils.json_schema_methods import JsonSchemaMethods


def test_get_key_value_by_given_path():
    input_dict = {"a": {"b": {"c": 1}}}
    keys = ["a", "b", "c"]

    # Test case 1: Check returned value when as_pointer is False (default)
    returned_value = JsonSchemaMethods.get_key_value_by_given_path(input_dict, keys)
    expected_value = 1
    assert (
        returned_value == expected_value
    ), f"Expected {expected_value}, but got {returned_value}"

    # Test case 2: Check returned value when as_pointer is True
    returned_value = JsonSchemaMethods.get_key_value_by_given_path(
        input_dict, keys, as_pointer=True
    )
    expected_value = 1
    assert (
        returned_value == expected_value
    ), f"Expected {expected_value}, but got {returned_value}"
