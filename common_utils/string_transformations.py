class StringTransformations:
    def recursion_lower(self, x: any) -> any:
        """this method transform all characters of the given object to lower case

        Args:
            x (any): any python object

        Returns:
            any: the python object after lower transformation
        """
        if type(x) is str:
            return x.lower()
        elif type(x) is list:
            return [self.recursion_lower(i) for i in x]
        elif type(x) is dict:
            return {
                self.recursion_lower(k): self.recursion_lower(v) for k, v in x.items()
            }
        else:
            return x
