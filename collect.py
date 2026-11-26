import json,re,hashlib,urllib.request,urllib.parse,datetime,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
KST=datetime.timezone(datetime.timedelta(hours=9))
NOW=datetime.datetime.now(KST); TODAY=NOW.date().isoformat()
BOARDS={'BoschGroup':'Bosch','Aumovio':'AUMOVIO','RenesasElectronics':'Renesas Electronics'}
RULES=[(100,r'\bmotor\b|모터|전동기|electric drive','모터 개발'),(95,r'전동화|구동시스템|powertrain|electrification','전동화'),(92,r'\bewp\b|\bpump\b|펌프|thermal management|열관리','펌프·열관리'),(90,r'mechanical|기구|기계설계|구조설계','기계·기구 설계'),(85,r'validation|test engineer|시험|검증|신뢰성','시험검증'),(83,r'\bcfd\b|\bcae\b|\bfea\b|유동해석|열유동|구조해석','CAE·열유동'),(80,r'fuel cell|연료전지|수소|hydrogen','수소연료전지'),(76,r'robot|로봇|항공|propulsion|aerospace','로봇·항공'),(70,r'자동차|automotive|r&d|연구개발|설계|engineer','기술 개발')]
def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'CareerRadar/2.1','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def date(v):
    m=re.match(r'^(\d{4})[-./]?(\d{2})[-./]?(\d{2})',str(v or ''))
    if not m:return ''
    try:return datetime.date(*map(int,m.groups())).isoformat()
    except ValueError:return ''
def make(key,company,title,typ,start,end,url,loc='',experience=''):
    start,end=date(start),date(end)
    if not title or not company or not url.startswith('https://') or (end and end<TODAY) or (start and start>TODAY):return None
    fit,why=next(((n,w) for n,p,w in RULES if re.search(p,title,re.I)),(0,'기타 직무'))
    if not fit:return None
    if re.search(r'\bsenior\b|\bsr\b|\blead\b|\bprincipal\b|\bmanager\b|팀장|수석',title,re.I):fit=max(0,fit-25);elig='확인 필요';why+=' · 선임 직급 확인'
    elif re.search(r'신입|인턴|entry.level|intern|graduate',title,re.I):elig='신입 포함'
    else:elig='확인 필요'
    return dict(id=hashlib.sha256(key.encode()).hexdigest()[:16],company=company,role=title,type=typ,start=start,end=end,fit=fit,elig=elig,reason=why+' · 제목 기반 평가, 필수 자격 원문 확인'+(' · '+loc if loc else ''),url=url)
def smart(board,company):
    out=[];offset=0
    while True:
        q=urllib.parse.urlencode({'country':'kr','limit':100,'offset':offset})
        data=fetch('https://api.smartrecruiters.com/v1/companies/'+board+'/postings?'+q)
        rows=data['content']
        if not isinstance(rows,list):raise ValueError('invalid list')
        for p in rows:
            l=p.get('location') or {}
            if str(l.get('country','')).lower() not in ('kr','kor','korea','south korea','republic of korea'):continue
            pid=str(p.get('id',''))
            if not pid:continue
            j=make(board+pid,company,str(p.get('name','')),'외국계','','','https://jobs.smartrecruiters.com/'+board+'/'+pid,str(l.get('city','')),str((p.get('experienceLevel') or {}).get('label','')))
            if j:
                j.update(published=date(p.get('releasedDate')),checkedAt=NOW.isoformat(timespec='seconds'),source='공식 채용 API',experienceLabel=str((p.get('experienceLevel') or {}).get('label','')))
                out.append(j)
        offset+=len(rows)
        if 'totalFound' not in data:raise ValueError('pagination metadata missing')
        total=int(data['totalFound'])
        if not rows and offset<total:raise ValueError('incomplete pagination')
        if offset>=total:return out
        if offset>=2000:raise ValueError('pagination limit')
def work24():
    import xml.etree.ElementTree as ET
    key=os.environ.get('WORK24_AUTH_KEY','')
    if not key or os.environ.get('WORK24_PUBLISH_ALLOWED')!='yes':raise ValueError('not authorized')
    out=[]
    for code,typ in [('10','대기업'),('40','중견기업'),('50','외국계')]:
        for page in range(1,51):
            args=urllib.parse.urlencode(dict(authKey=key,callTp='L',returnType='XML',startPage=page,display=100,coClcd=code))
            req=urllib.request.Request('https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L21.do?'+args)
            with urllib.request.urlopen(req,timeout=25) as r:root=ET.fromstring(r.read())
            total=int(root.findtext('.//total'));rows=root.findall('.//dhsOpenEmpInfo') or root.findall('.//empWanted')
            if total and not rows:raise ValueError('unexpected schema')
            for p in rows:
                g=lambda k:p.findtext(k,'')
                if not date(g('empWantedEndt')):continue
                j=make('work24'+g('empSeqno'),g('empBusiNm'),g('empWantedTitle'),typ,g('empWantedStdt'),g('empWantedEndt'),g('empWantedHomepgDetail') or g('empWantedMobileUrl'),experience=g('empWantedTypeNm'))
                if j:
                    j.update(checkedAt=NOW.isoformat(timespec='seconds'),source='고용24')
                    out.append(j)
            if page*100>=total:break
        else:raise ValueError('pagination limit')
    return out
def run():
    jobs=[];status={}
    def one(x):
        board,company=x
        try:return company,smart(board,company),'정상'
        except Exception as e:return company,[],'조회 실패: '+type(e).__name__
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name,rows,state in pool.map(one,BOARDS.items()):jobs+=rows;status[name]=state
    if os.environ.get('WORK24_AUTH_KEY') and os.environ.get('WORK24_PUBLISH_ALLOWED')=='yes':
        try:jobs+=work24();status['고용24']='정상'
        except Exception as e:status['고용24']='조회 실패: '+type(e).__name__
    else:status['고용24']='미연동 (게시 허가 및 인증 필요)'
    unique={j['id']:j for j in jobs}
    result={'updated':NOW.isoformat(timespec='seconds'),'status':status,'jobs':sorted(unique.values(),key=lambda j:-j['fit'])}
    Path(__file__).with_name('jobs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Collected',len(unique),'jobs',status)
if __name__=='__main__':run()
