Structure:
- tests should be `tests/T{spec_number}-{test_number}-{feature_name}-{test_name}.py`
- Each language/format should be `src/py/onto/{feature}/[model.py,parser.py,formatter.py,operations.py]` ,where model is the data structures, parser the parser, formatter the canonical formatter, and operations a collection of functions/operations to run on. Try to organise operations under an Operator class that can take a context with parameters/contextual information across operations.
