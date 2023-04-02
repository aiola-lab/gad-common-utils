import json
import re


class GeneratePythonObjectFromSqlDataType:
    def generate_python_object_from_sql_data_type(self, sql_data_type: str) -> any:
        """this method takes a sql data type and returns the corresponding python object (empty)
        e.g. string will be returned as empty string "", arrat as empty list and so on

        Args:
            sql_data_type (str): a sql data type

        Returns:
            any: an empty python object that represents the sql data type
        """
        x = (
            sql_data_type.replace("string", '""')
            .replace("boolean", "False")
            .replace("bigint", "0")
            .replace("int", "0")
        )

        # replace decimal(x, y) with 0
        x = re.sub("decimal\(\d+(,\s\d+)\)", "0", x)

        # wrap each word followed by colon in double quotes (using regex backreferences: "\1" means the first capturing group)
        x = re.sub(r"(\w+):", r'"\1":', x)

        x = GeneratePythonObjectFromSqlDataType.replace_array_and_struct_keywords_with_suitable_brackets(
            x
        )

        # boolean value can't be converted to json
        x = False if x == "False" else json.loads(x)

        return x

    def replace_array_and_struct_keywords_with_suitable_brackets(col_type: str) -> str:
        """this method replace the array<> and struct<> keywords with their corresponding chars in python
        e.g. "array<>" becomes [] and "struct<>" becomes {}

        Args:
            col_type (str): a sql data type

        Returns:
            str: adjusted sql data type
        """
        # get the indices of each per of brackets
        brackets_indices = Helpers.find_parens(col_type)

        # keep running until there are no more "<" to replace ("<" is the begining of array/struct)
        while col_type.find("<") != -1:
            open_parens_ind = col_type.find("<")
            close_parens_ind = brackets_indices[open_parens_ind]

            # get the first index of array/struct
            x = re.search(r"(\w+)<", col_type).group()

            if x == "array<":
                col_type = Helpers.replace_str_index(col_type, close_parens_ind, "]")
                col_type = col_type.replace(x, "[", 1)
            elif x == "struct<":
                col_type = Helpers.replace_str_index(col_type, close_parens_ind, "}")
                col_type = col_type.replace(x, "{", 1)

            # recalculate the indices of the open and close brackets
            brackets_indices = Helpers.find_parens(col_type)

        return col_type


class Helpers:
    def find_parens(s: str, brackets_type: list = ["<", ">"]) -> dict:
        """this method get a string and returns a dict of the open and closing indcies of each pair of brackets in the given string

        Args:
            s (str): string to search for brackets
            brackets_type (list, optional): the type of open/close brackets to look for. Defaults to ['<', '>'].

        Raises:
            IndexError: missing closing bracket
            IndexError: missing opening bracket

        Returns:
            dict: indices of open/close brackets.
            the key is the opening bracket index, the value is the closing bracket index
        """
        indices = {}
        pstack = []

        for i, c in enumerate(s):
            if c == brackets_type[0]:
                pstack.append(i)
            elif c == brackets_type[1]:
                if len(pstack) == 0:
                    raise IndexError("No matching closing parens at: " + str(i))
                indices[pstack.pop()] = i

        if len(pstack) > 0:
            raise IndexError("No matching opening parens at: " + str(pstack.pop()))

        return indices

    def replace_str_index(text: str, index: int = 0, replacement: str = "") -> str:
        return text[:index] + replacement + text[index + 1 :]


class GenerateSqlDataType:
    def generate_sql_data_type(python_object: any) -> str:
        """the reverse action of generate_python_object() method.
        this method takes a python object and returns a string representation of it in the form of sql data type

        Args:
            python_object (any): any python object

        Returns:
            str: sql data type
        """
        x = json.dumps(python_object)

        # TODO: collect the default values per type and use them instead. e.g. if the default value of a number
        # is -1, we won't support it
        x = (
            x.replace('""', "string")
            .replace("false", "boolean")
            .replace("true", "boolean")
            .replace("0", "decimal(38, 9)")
            .replace("[", "array<")
            .replace("]", ">")
            .replace("{", "struct<")
            .replace("}", ">")
            .replace('"', "")
            .replace(" ", "")
        )

        return x
