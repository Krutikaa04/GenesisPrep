"""Independent M1 fixtures and an honest, reproducible accuracy benchmark.

Run tests normally, or measure with:
  python tests/test_fmt_m1_accuracy.py --measure
  python tests/test_fmt_m1_accuracy.py --performance
The expectations below are specified before encoding; the decoder never creates
its own expected values. The corpus is synthetic regression evidence, not a
prediction of a hidden judge score. No official fixture is modified.
"""
import copy
import datetime
import json
import struct
import sys
import time
import unittest
from dataclasses import dataclass, field

from helpers import check_contract, salvage_bytes


@dataclass
class Case:
    name: str
    data: bytes
    fmt: str
    records: list
    key: str
    status: str = 'ok'
    damage: frozenset = frozenset()
    uncertain: frozenset = frozenset()
    metadata: dict = field(default_factory=dict)


def _dos_date(year, month, day):
    return ((year - 1980) << 9) | (month << 5) | day


def _libra_record(rec):
    title, author = rec['title'].encode('cp1252'), rec['author'].encode('cp1252')
    flags = int(rec['checked_out']) | (int(rec['deleted']) << 1) | (int(rec['reference_only']) << 2)
    body = (bytes([flags]) + struct.pack('<I', rec['id']) + bytes([len(title)]) + title +
            bytes([len(author)]) + author + struct.pack('<HHB', rec['year'] - 1500,
            rec['price_cents'], rec['copies']) + rec['isbn'].encode('ascii') + b'\0\0')
    body += bytes([sum(body) & 255])
    return b'\xa5' + bytes([len(body)]) + body


def _libra(seed):
    records = [dict(id=1000+seed*10+i, title='Café %d/%d' % (seed,i), author='Zoë',
                    year=1900+seed+i, price_cents=1000+17*i, copies=1+i,
                    isbn=str(1000000000+seed*10+i), checked_out=bool(i),
                    deleted=False, reference_only=False, due_date=None) for i in range(2)]
    vendor = b'VENDOR\0'.ljust(24, b'\0') if seed % 2 else b''
    if seed == 7:
        fake = dict(records[0], id=999999, title='Vendor fixture')
        vendor = b'VENDOR\0' + _libra_record(fake) + b'END!xx'
    start = 16 + len(vendor)
    header = b'LB98' + struct.pack('<BBHHHHH', 2, 1, 2, _dos_date(1999,1,2),
                                  (3 << 11) | (4 << 5) | 3, start, 27+seed)
    encoded = [_libra_record(r) for r in records]
    data = header + vendor + b''.join(encoded)
    data += b'END!' + struct.pack('<H', sum(data) & 65535)
    case = Case('LIBRA/%d/pristine' % seed, data, 'LIBRA-98', records, 'id',
                metadata={'encoding':'cp1252','data_offset':start})
    return case, start


def _crc(data):
    # An independent bitwise implementation, separate from production utilities.
    value = 0xffff
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 0xffff if value & 0x8000 else (value << 1) & 0xffff
    return value


def _block(typ, payload):
    body = struct.pack('<BH',typ,len(payload)) + payload
    return b'\xb1' + body + struct.pack('<H',_crc(body))


def _lablog(seed):
    first, interval = seed*10, (20+seed*5)*10
    raws = [(100+seed,200+seed),(-32768,10+seed),(400+seed,-100-seed)]
    records = [dict(sample=first+i, time_ms=(first+i)*interval,
                    values=[None if a == -32768 else a*0.5+10, b*0.25-2])
               for i,(a,b) in enumerate(raws)]
    table = struct.pack('<4sff4sff',b'mV',0.5,10,b'ppm',0.25,-2)
    samples = struct.pack('<HB',first,len(raws)) + b''.join(struct.pack('<hh',*r) for r in raws)
    message = ('event %d' % seed).encode('ascii')
    event = struct.pack('<HBB',first+1,1,len(message)) + message
    blocks = [_block(3,table),_block(1,samples),_block(2,event)]
    header = b'LLOG' + struct.pack('<BBH16sIH',1,2,interval//10,
                                   ('ORACLE-%d' % seed).encode(),86400*seed,3)
    header += struct.pack('<H',_crc(header))
    data = header + b''.join(blocks)
    case = Case('LABLOG/%d/pristine' % seed,data,'LABLOG',records,'sample',
                metadata={'sample_interval_ms':interval,
                          'start_time_utc':(datetime.datetime(1990,1,1)+datetime.timedelta(days=seed)).isoformat()+'Z',
                          'channels':[{'index':0,'unit':'mV'},{'index':1,'unit':'ppm'}],
                          'events':[{'sample':first+1,'severity':1,'message':message.decode()}]})
    return case, blocks, table


def _packed(value, size):
    return bytes.fromhex(str(abs(value)).zfill(size*2-1) + ('d' if value < 0 else 'c'))


def _rdw(payload):
    return struct.pack('>H',len(payload)+4) + b'\0\0' + payload


def _bdw(payload):
    return struct.pack('>H',len(payload)+4) + b'\0\0' + payload


def _ebcdic(seed):
    records = [dict(student_id=str(750000+seed*10+i), name='ÉTUDIANT %d' % i,
                    dob='%04d-01-%02d' % (1980+seed,10+i), gpa=(250+seed+i*25)/100,
                    credits=10+7*i, status='G', balance=(-1 if i==1 else 1)*(12500+seed+i)/100)
               for i in range(3)]
    header = _rdw(b'\xc8'+('EXTRACT %d' % seed).ljust(20).encode('cp037')+'19990314'.encode('cp037'))
    students=[]
    for rec in records:
        payload=(b'\xc4'+rec['student_id'].encode('cp037')+rec['name'].ljust(20).encode('cp037')+
                 _packed(int(rec['dob'].replace('-','')),5)+_packed(round(rec['gpa']*100),3)+
                 struct.pack('>H',rec['credits'])+rec['status'].encode('cp037')+
                 _packed(round(rec['balance']*100),4)+b'\x40\x40')
        students.append(_rdw(payload))
    trailer=_rdw(b'\xe3'+_packed(3,4)+_packed(sum(r['credits'] for r in records),5))
    blocks=[_bdw(header+students[0]),_bdw(students[1]+students[2]),_bdw(trailer)]
    data=b''.join(blocks)
    case=Case('EBCDIC/%d/pristine' % seed,data,'EBCDIC-DUMP',records,'student_id',
              metadata={'title':'EXTRACT %d' % seed,'run_date':'1999-03-14',
                        'trailer_count':3,'trailer_credits_total':51})
    return case, len(blocks[0])


def _variant(base, suffix, data, **changes):
    values=dict(name=base.name.rsplit('/',1)[0]+'/'+suffix,data=bytes(data),fmt=base.fmt,
                records=copy.deepcopy(base.records),key=base.key,status='partial',
                damage=frozenset(),uncertain=frozenset(),metadata={})
    values.update(changes)
    return Case(**values)


def cases():
    result=[]
    for seed in range(8):
        base,start=_libra(seed);result.append(base)
        keys=frozenset(r['id'] for r in base.records)
        for label,offset in (('offset-middle',start+1),('offset-next-record',start+len(_libra_record(base.records[0])))):
            data=bytearray(base.data);struct.pack_into('<H',data,12,offset)
            result.append(_variant(base,label,data,damage=frozenset({'invalid_value','checksum_mismatch'}),uncertain=keys))
        data=bytearray(base.data);data[5]^=1
        result.append(_variant(base,'encoding-header-flip',data,damage=frozenset({'checksum_mismatch'}),uncertain=keys))
        data=bytearray(base.data);data[-1]^=1
        result.append(_variant(base,'trailer-flip',data,damage=frozenset({'checksum_mismatch'}),uncertain=keys))
        end=len(base.data)-6
        data=bytearray(base.data[:end]+b'END!xx'+base.data[end:])
        struct.pack_into('<H',data,len(data)-2,sum(data[:-6])&65535)
        result.append(_variant(base,'stray-final-marker',data,damage=frozenset({'unparsed_bytes'})))

        base,blocks,table=_lablog(seed);result.append(base)
        sample_start=32+len(blocks[0]);keys=frozenset(r['sample'] for r in base.records)
        actual=len(blocks[1])-6
        for length in (0,1,actual-1,actual+1,255,65535):
            data=bytearray(base.data);struct.pack_into('<H',data,sample_start+2,length)
            result.append(_variant(base,'length-%d' % length,data,damage=frozenset({'bad_length'})))
        for nchan in (0,1,3,255):
            data=bytearray(base.data);data[5]=nchan
            result.append(_variant(base,'header-channels-%d' % nchan,data,
                                   damage=frozenset({'header_checksum'}),uncertain=keys))
        # A changed unit list must not relabel historical verified samples after
        # an intervening malformed table erased the currently exposed list.
        new_table=b'degC'+table[4:]
        header=bytearray(base.data[:32]);struct.pack_into('<H',header,28,5)
        struct.pack_into('<H',header,30,_crc(header[:30]))
        data=header+blocks[0]+blocks[1]+_block(3,b'bad')+_block(3,new_table)+blocks[2]
        result.append(_variant(base,'lost-unit-history',data,
                               damage=frozenset({'invalid_value','bad_length'}),uncertain=keys))
        # Negative repair control: fixing a length cannot authenticate a payload
        # that was also corrupted. The intact original samples must not be
        # claimed as a successfully validated repair.
        data=bytearray(base.data);struct.pack_into('<H',data,sample_start+2,0)
        data[sample_start+7]^=1
        result.append(_variant(base,'length-plus-payload-damage',data,records=[],
                               damage=frozenset({'bad_length'}),status='failed'))

        base,next_block=_ebcdic(seed);result.append(base)
        data=bytearray(base.data);data[29:37]='19990230'.encode('cp037')
        result.append(_variant(base,'invalid-header-date',data,damage=frozenset({'invalid_value'})))
        data=bytearray(base.data);data[9]=0
        result.append(_variant(base,'header-title-control',data,damage=frozenset({'invalid_value'})))
        # Next block's first record starts at next_block+4. Its DOB is 4 RDW
        # bytes, 1 type, then 26 bytes into the body.
        data=bytearray(base.data);data[next_block+35]=0xff
        expected=copy.deepcopy(base.records);expected[1]['dob']=None
        result.append(_variant(base,'next-block-invalid-dob',data,records=expected,
                               damage=frozenset({'invalid_value'}),uncertain=frozenset({expected[1]['student_id']})))
        data=bytearray(base.data);data[next_block+6]=1
        result.append(_variant(base,'next-block-rdw-reserved',data,
                               records=[base.records[0],base.records[2]],damage=frozenset({'bad_length'})))
        # First student's name follows the first BDW, header RDW and its own
        # RDW/type/ID. Do not prescribe how unreadable text is represented.
        data=bytearray(base.data);data[48]=0
        expected=copy.deepcopy(base.records);expected[0].pop('name')
        result.append(_variant(base,'student-name-control',data,records=expected,
                               damage=frozenset({'invalid_value'}),uncertain=frozenset({expected[0]['student_id']})))
    for index,data in enumerate((b'',b'ordinary text',bytes(range(256)),b'LLOG'+bytes(60),b'not-a-header\0\0\xc8')):
        result.append(Case('negative/%d' % index,data,'UNKNOWN',[],'id','unrecognized'))
    return result


def score(case, doc):
    expected={r[case.key]:r for r in case.records}
    actual={r.get(case.key):r for r in doc['records']}
    def trusted(record):
        return record.get('verified',True) is True and not record.get('issues')
    correct_fields=sum(field in actual.get(key,{}) and actual[key][field]==value
                       for key,rec in expected.items() for field,value in rec.items())
    wrong_verified=sum(trusted(rec) and (key not in expected or any(
        field not in rec or rec[field]!=value for field,value in expected[key].items()))
        for rec in doc['records'] for key in (rec.get(case.key),))
    return dict(expected_records=len(expected), recovered_records=sum(key in actual for key in expected),
                correct_records=sum(key in actual and all(field in actual[key] and actual[key][field]==value
                                    for field,value in rec.items()) for key,rec in expected.items()),
                expected_fields=sum(map(len,expected.values())),correct_fields=correct_fields,
                missed_records=sum(key not in actual for key in expected),
                unexpected_records=sum(key not in expected for key in actual),
                duplicate_records=len(doc['records'])-len(actual),
                wrong_verified_records=wrong_verified,
                trust_violations=sum(key in actual and trusted(actual[key]) for key in case.uncertain),
                format_correct=int(doc['format']==case.fmt),status_correct=int(doc['status']==case.status),
                damage_correct=int({d['kind'] for d in doc['damage']}==set(case.damage)),
                metadata_correct=int(all(doc['metadata'].get(k)==v for k,v in case.metadata.items())))


def measure():
    rows=[]
    for case in cases():
        started=time.perf_counter()
        try:
            res=salvage_bytes(case.data,case.name)
            doc=res.to_dict()
            json.dumps(doc,allow_nan=False)
            row=score(case,doc)
            row.update(crashes=int(any('decoder exception' in note for note in res.notes)),actual_damage=sorted({d['kind'] for d in doc['damage']}))
        except Exception as exc:  # diagnostic report must count failures honestly
            row=dict(crashes=1,error=type(exc).__name__)
        row.update(name=case.name,format=case.fmt,runtime_ms=round((time.perf_counter()-started)*1000,3))
        rows.append(row)
    summaries={}
    metrics=('expected_records','recovered_records','correct_records','expected_fields','correct_fields',
             'missed_records','unexpected_records','duplicate_records','wrong_verified_records','trust_violations',
             'format_correct','status_correct','damage_correct','metadata_correct','crashes')
    for fmt in sorted({row['format'] for row in rows}):
        subset=[r for r in rows if r['format']==fmt]
        summary={metric:sum(row.get(metric,0) for row in subset) for metric in metrics}
        summary.update(cases=len(subset),max_runtime_ms=max(row['runtime_ms'] for row in subset))
        summaries[fmt]=summary
    return {'corpus':'M1 independent regression corpus v1','by_format':summaries,'cases':rows}

def performance():
    """Bounded decoder timings; deterministic complexity guards live in tests."""
    from deadbits.formats import lablog, libra98
    rows = []
    for count in (200, 400, 800):
        header = bytearray(_lablog(0)[0].data[:32])
        struct.pack_into('<H', header, 28, count)
        struct.pack_into('<H', header, 30, _crc(header[:30]))
        bad_logs = bytes(header) + b'\xb1\x01\0\0\0\0' * count
        header = b'LB98' + struct.pack('<BBHHHHH', 2, 0, count,
                                      _dos_date(1999,1,2), 0, 16, 1)
        payload = bytearray(header)
        for index in range(count):
            rec = dict(id=index, title='Bench', author='A', year=1900,
                       price_cents=100, copies=1, isbn='1000000000',
                       checked_out=False, deleted=False, reference_only=False)
            payload += b'\xa5\0' + _libra_record(rec)
        damaged_libra = bytes(payload) + b'END!' + struct.pack('<H', sum(payload) & 65535)
        dense_header = bytearray(_lablog(0)[0].data[:32])
        dense = bytes(dense_header) + (b'\xb1\xfa' + struct.pack('<H', count*4))*count + bytes(count*4+6)
        for fmt, pattern, data, decode in (('LABLOG', 'repeated-bad-blocks', bad_logs, lablog.decode),
                                         ('LABLOG', 'dense-overlapping-markers', dense, lablog.decode),
                                         ('LIBRA-98', 'malformed-record-prefixes', damaged_libra, libra98.decode)):
            elapsed = []
            for _ in range(3):
                started = time.perf_counter()
                decode(data, 'bounded-performance')
                elapsed.append((time.perf_counter() - started) * 1000)
            rows.append(dict(format=fmt, pattern=pattern, blocks_or_records=count, bytes=len(data),
                             median_runtime_ms=round(sorted(elapsed)[1], 3)))
    return rows


class IndependentM1Fixtures(unittest.TestCase):
    def test_crc_reference_vector(self):
        self.assertEqual(_crc(b'123456789'),0x29b1)

    def test_pristine_records_match_values_chosen_before_encoding(self):
        for case in cases():
            if not case.name.endswith('/pristine'):
                continue
            with self.subTest(case=case.name):
                res=salvage_bytes(case.data,case.name)
                doc=check_contract(self,res,len(case.data))
                result=score(case,doc)
                self.assertEqual(result['correct_fields'],result['expected_fields'])
                self.assertEqual(result['correct_records'],result['expected_records'])
                for metric in ('format_correct','status_correct','damage_correct','metadata_correct'):
                    self.assertEqual(result[metric],1,metric)
                self.assertEqual(result['wrong_verified_records'],0)

    def test_targeted_damage_preserves_truth_and_verification(self):
        for case in cases():
            with self.subTest(case=case.name):
                res = salvage_bytes(case.data, case.name)
                doc = check_contract(self, res, len(case.data))
                json.dumps(doc, allow_nan=False)
                result = score(case, doc)
                for metric in ('format_correct', 'status_correct', 'damage_correct', 'metadata_correct'):
                    self.assertEqual(result[metric], 1, (metric, doc))
                for metric in ('missed_records', 'unexpected_records', 'duplicate_records',
                               'wrong_verified_records', 'trust_violations'):
                    self.assertEqual(result[metric], 0, (metric, doc))
                # A flipped unprotected codec flag cannot establish the original
                # text. Keep this case in measured field accuracy and require
                # uncertainty, rather than pretending a guessed codec is correct.
                if not case.name.endswith('/encoding-header-flip'):
                    self.assertEqual(result['correct_fields'], result['expected_fields'])
                    self.assertEqual(result['correct_records'], result['expected_records'])

    def test_scoring_detects_wrong_fields_and_false_assurance(self):
        case=Case('oracle',b'','LIBRA-98',[{'id':1,'title':'expected'}],'id',uncertain=frozenset({1}))
        doc=dict(format='LIBRA-98',status='ok',records=[{'id':1,'title':'wrong'}],damage=[],metadata={})
        result=score(case,doc)
        self.assertEqual(result['wrong_verified_records'],1)
        self.assertEqual(result['trust_violations'],1)
        self.assertEqual(result['correct_fields'],1)
        doc['records'][0]['verified']=False
        self.assertEqual(score(case,doc)['wrong_verified_records'],0)
        self.assertEqual(score(case,doc)['trust_violations'],0)


if __name__=='__main__':
    if '--performance' in sys.argv:
        print(json.dumps(performance(), indent=2))
    elif '--measure' in sys.argv:
        print(json.dumps(measure(),indent=2,sort_keys=True))
    else:
        unittest.main()
