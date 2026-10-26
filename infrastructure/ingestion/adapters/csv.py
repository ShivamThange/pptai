"""Lexical CSV records with physical line spans; never infer numeric types."""
import csv
import io
from itertools import islice
from pathlib import Path
from contracts.ingestion_schema import IngestionError, ParseFinding
from infrastructure.ingestion.detection import decode_text
from application.jobs.job_context import check
from .common import base, block, table, finish


def delimiter_for(text):
    candidates = []
    for delimiter in ',;\t|':
        try:
            rows = list(islice(csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True), 30))
            widths = {len(row) for row in rows if row}
            if widths and max(widths) > 1:
                candidates.append(delimiter)
        except csv.Error:
            if delimiter in text:
                candidates.append(delimiter)
    if len(candidates) != 1:
        raise IngestionError('CSV_DELIMITER_REQUIRED', 'Choose the CSV delimiter explicitly; automatic detection is ambiguous.')
    return candidates[0]


def extract(source, output, options, *, context=None, limits=None):
    text, _ = decode_text(Path(source).read_bytes(), options.encoding)
    Path(output, 'decoded_source.txt').write_bytes(text.encode('utf-8'))
    ir, records = base(source), []
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=options.csv_delimiter, strict=True)
    previous = 0
    try:
        for index, row in enumerate(reader, 1):
            check(context)
            records.append({'record_index': index, 'line_start': previous + 1,
                            'line_end': reader.line_num, 'cells': row})
            previous = reader.line_num
    except csv.Error:
        ir['findings'].append(ParseFinding(code='CORRUPT_SOURCE', severity='error',
                                         message='Malformed CSV quoting; correct the records.', blocks_generation=True).model_dump())
    width = len(records[0]['cells']) if records else 0
    ragged = [r['record_index'] for r in records if len(r['cells']) != width]
    if ragged:
        ir['findings'].append(ParseFinding(code='CSV_ROW_WIDTH', severity='error',
            message='CSV record widths differ; correct the listed records.', location={'records': ragged}, blocks_generation=True).model_dump())
    all_cells = []
    for record in records:
        cells = []
        for col, value in enumerate(record['cells'], 1):
            ref = f"{ir['document_id']}:csv:record:{record['record_index']}:column:{col}"
            ir['source_item_ids'].append(ref)
            loc = {'kind': 'csv_cell', 'document_id': ir['document_id'], 'source_id': ref,
                   **{k: record[k] for k in ('record_index', 'line_start', 'line_end')}, 'column_index': col}
            cells.append({'row': record['record_index'] - 1, 'column': col - 1, 'text': value,
                          'lexical_value': value, 'raw_value': value, 'value_type': 'string',
                          'column_header': bool(options.csv_has_header and record['record_index'] == 1),
                          'source_refs': [ref], 'locations': [loc]})
            block(ir, ref, value, loc, kind='csv_cell')
        all_cells.append(cells)
    data_records = records[1:] if options.csv_has_header else records
    if not ragged and not ir['findings']:
        for start in range(0, len(data_records), 200):
            check(context)
            rows = data_records[start:start + 200]
            data_cells = []
            if options.csv_has_header:
                data_cells.extend({**c, 'row': 0} for c in all_cells[0])
            for ordinal, record in enumerate(rows, int(options.csv_has_header)):
                data_cells.extend({**c, 'row': ordinal} for c in all_cells[record['record_index'] - 1])
            table(ir, output, f"{ir['document_id']}:csv:table:{start // 200 + 1}",
                  {'headers': records[0]['cells'] if options.csv_has_header else [],
                   'rows': [r['cells'] for r in rows], 'cells': data_cells})
    if not data_records or not any(any(v.strip() for v in r['cells']) for r in data_records):
        ir['findings'].append(ParseFinding(code='NO_USABLE_CONTENT', severity='error',
                                         message='CSV contains no data records.', blocks_generation=True).model_dump())
    return finish(ir, output, {'records': records, 'delimiter': options.csv_delimiter,
                              'has_header': options.csv_has_header})
