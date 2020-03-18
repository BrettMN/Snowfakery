from io import StringIO
import unittest
from unittest import mock
from snowfakery.data_generator import generate
from test_parse_samples import find_row

simple_parent = """                     #1
- object: A                             #2
  fields:                               #3
    B:                                  #4
        object: B                       #5
        fields:                         #6
            A_ref:                      #7
                reference: A            #8
    """

simple_parent_list = """                #1
- object: A                             #2
  fields:                               #3
    B:                                  #4
      - object: B                       #5
        fields:                         #6
            A_ref:                      #7
                reference: A            #8
    """


ancestor_reference = """                #1
- object: A                             #2
  fields:                               #3
    B:                                  #4
      - object: B                       #5
        fields:                         #6
            C:                          #7
               object: C                #8
               fields:                  #9
                  A_ref:                #10
                     reference: A       #11
    """

reference_from_friend = """             #1
- object: A                             #2
  friends:                              #3
      - object: B                       #4
        fields:                         #5
            A_ref:                      #6
                reference: A            #7
    """

write_row_path = "snowfakery.output_streams.DebugOutputStream.write_single_row"


class TestReferences(unittest.TestCase):
    @mock.patch(write_row_path)
    def test_simple_parent(self, write_row):
        generate(StringIO(simple_parent), {}, None)

        a_values = find_row("A", {}, write_row.mock_calls)
        b_values = find_row("B", {}, write_row.mock_calls)
        id_a = a_values["id"]
        reference_b = a_values["B"]
        id_b = b_values["id"]
        reference_a = b_values["A_ref"]
        assert f"A({id_a})" == reference_a
        assert f"B({id_b})" == reference_b

    @mock.patch(write_row_path)
    def test_simple_parent_list_child(self, write_row):
        generate(StringIO(simple_parent_list), {}, None)

        a_values = find_row("A", {}, write_row.mock_calls)
        b_values = find_row("B", {}, write_row.mock_calls)
        id_a = a_values["id"]
        reference_b = a_values["B"]
        id_b = b_values["id"]
        reference_a = b_values["A_ref"]
        assert f"A({id_a})" == reference_a
        assert f"B({id_b})" == reference_b

    @mock.patch(write_row_path)
    def test_ancestor_reference(self, write_row):
        generate(StringIO(ancestor_reference), {}, None)

        a_values = find_row("A", {}, write_row.mock_calls)
        c_values = find_row("C", {}, write_row.mock_calls)
        id_a = a_values["id"]
        reference_a = c_values["A_ref"]
        assert f"A({id_a})" == reference_a

    @mock.patch(write_row_path)
    def test_reference_from_friend(self, write_row):
        generate(StringIO(reference_from_friend), {}, None)

        a_values = find_row("A", {}, write_row.mock_calls)
        b_values = find_row("B", {}, write_row.mock_calls)
        id_a = a_values["id"]
        reference_a = b_values["A_ref"]
        assert f"A({id_a})" == reference_a
