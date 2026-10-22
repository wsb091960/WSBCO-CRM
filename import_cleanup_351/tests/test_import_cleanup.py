import csv
import io
import json
from sqlalchemy import select
from test_imports_v35 import setup, stage, preview, commit
from app.models import Lead
from app.imports_v35 import COOKIE, ContactImportBatch
from app.services.contact_import import signature, read_file, suggested_mapping


def test_400_states_and_leading_zero_zip(setup):
    client, sessions = setup
    data = 'First,Last,Email,State,ZIP\n' + ''.join(f'Person{i},Example,p{i}@example.test,{["or", " OR ", "Oregon", "oregon"][i%4]},00501\n' for i in range(400))
    url = stage(client, data.encode())
    preview(client, url, ['first_name','last_name','email','state','zip_code'])
    cleaned = list(csv.DictReader(io.StringIO(client.get(url+'/cleaned.csv').text)))
    assert len(cleaned) == 400
    assert all(r['State']=='OR' and r['ZIP']=='00501' for r in cleaned)
    assert commit(client,url).status_code == 200
    with sessions() as db:
        assert len(db.scalars(select(Lead)).all()) == 400


def test_bulk_preview_rejected_download_and_retry(setup):
    client, sessions = setup
    data = b'First,Last,Email,State,Status,ZIP\nAnn,Example,ann@example.test,Oregon,No Answer,00501\nBob,Example,bob@example.test,or,No Answer,00501\nCat,Example,cat@example.test,XX,New,00501\n'
    fields = ['first_name','last_name','email','state','status','zip_code']
    url = stage(client,data)
    preview(client,url,fields)
    with sessions() as db:
        result=json.loads(db.get(ContactImportBatch,url.split('/')[-1]).payload)['preview']
        assert result['counts']['error']==3
        assert sorted(len(g['rows']) for g in result['error_groups'])==[1,2]
    form={'csrf':client.cookies[COOKIE],'revision':signature(result),'field':'status','old':'No Answer','replacement':'Attempt Again'}
    response=client.post(url+'/correct',data=form)
    assert response.status_code==200
    assert client.post(url+'/correct',data=form).status_code==409
    assert 'No Answer' in client.get(url+'/original.csv').text
    with sessions() as db:
        assert not db.scalars(select(Lead)).all()
    commit(client,url)
    rejected=list(csv.DictReader(io.StringIO(client.get(url+'/errors.csv').text)))
    assert len(rejected)==1 and rejected[0]['First']=='Cat'
    assert json.loads(rejected[0]['Original source values (JSON)'])['State']=='XX'
    rejected[0]['State']='CA'
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(rejected[0]));writer.writeheader();writer.writerows(rejected)
    table=read_file('retry.csv',out.getvalue().encode())
    retry=stage(client,out.getvalue().encode())
    preview(client,retry,suggested_mapping(table['headers']))
    commit(client,retry);commit(client,retry)
    with sessions() as db:
        leads=db.scalars(select(Lead)).all()
        assert len(leads)==3
        assert {lead.status for lead in leads}=={'Attempt Again','New'}


def test_unknown_states_remain_errors_and_new_full_names(setup):
    client,sessions=setup
    url=stage(client,b'First,Last,State\nAnn,Example,West Virginia\nBob,Example,ZZ\nCat,Example,Orgeron\n')
    preview(client,url,['first_name','last_name','state'])
    with sessions() as db:
        result=json.loads(db.get(ContactImportBatch,url.split('/')[-1]).payload)['preview']
        assert result['counts']=={'create':1,'update':0,'skip':0,'error':2}
        assert result['rows'][0]['data']['state']=='WV'
