"""Key-free external search; fetch snippets only, never arbitrary URLs or private records."""
import html,re,json
from html.parser import HTMLParser
from urllib.request import Request,urlopen
from urllib.parse import urlencode,urlparse,parse_qs,unquote
class Results(HTMLParser):
    def __init__(self):super().__init__();self.items=[];self.capture=None;self.current=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);cls=a.get('class','')
        if tag=='a' and 'result__a' in cls:
            href=a.get('href','');p=urlparse(href);href=parse_qs(p.query).get('uddg',[href])[0]
            if urlparse(href).scheme not in ('https','http'):return
            self.current={'url':href,'title':'','snippet':''};self.items.append(self.current);self.capture='title'
        elif tag in ('a','div') and 'result__snippet' in cls and self.current:self.capture='snippet'
    def handle_endtag(self,tag):
        if tag in ('a','div'):self.capture=None
    def handle_data(self,data):
        if self.capture and self.current:self.current[self.capture]+=data

def lookup(facts,message):
    query=facts.get('public_query','');lower=query.lower()
    internal=bool(facts.get('requested_task_ids')) or any(v in lower for v in ('сотрудник','работник','мастер','рейтинг','оценк','наряд','отчёт','отчет','зарплат','бухгалтер','кто выполня','база дан','наша бд','нашей бд'))
    technical=any(v in lower for v in ('как ','почему ','интернет','найди','найти','инструкц','подшип','неисправ','ремонт','насос','конвейер'))
    if 'training' in facts or not facts.get('web_allowed') or internal or not technical or facts.get('documents_found'):return {'status':'not_used','sources':[]}
    if '[email]' in query or '[номер]' in query or 'Сотрудник #' in query:return {'status':'private_query_blocked','sources':[]}
    try:
        req=Request('https://html.duckduckgo.com/html/?'+urlencode({'q':query[:300]}),headers={'User-Agent':'Mozilla/5.0 NaryadAI/1.6'})
        with urlopen(req,timeout=15) as r:
            raw=r.read(1000001)
            if len(raw)>1000000:raise ValueError('Too large')
        parser=Results();parser.feed(raw.decode('utf-8',errors='replace'))
        sources=[{'title':s['title'].strip()[:200],'url':s['url'][:1000],'snippet':s['snippet'].strip()[:800]} for s in parser.items if s['snippet'].strip()][:4]
        return {'status':'found' if sources else 'no_results','sources':sources,'scope':'Фрагменты внешнего поиска, не проверенные сведения предприятия.'}
    except Exception:return {'status':'unavailable','sources':[],'note':'Внешний поиск недоступен. Не утверждай, что искал или нашёл источник.'}
