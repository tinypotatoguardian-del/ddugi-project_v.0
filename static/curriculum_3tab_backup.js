function renderCurriculumWrap_3tab(){
  // 중고등학생 / 대학생·취준 / 직장인·중년 3탭 버전
  window._curriculumTab3 = window._curriculumTab3 || 'teen';
  window._curriculumIdx3 = window._curriculumIdx3 || 0;

  const tabs = [
    { id:'teen',   label:'📚 중고등학생', desc:'AI 첫 만남부터 진로 탐색까지' },
    { id:'career', label:'💼 대학생·취준', desc:'공부·자소서·직무 연결하기' },
    { id:'work',   label:'🏢 직장인·중년', desc:'업무 보조·자동화·AX 설계' }
  ];

  const levels = {
    teen: [
      {lv:'LV.0', icon:'🌱', title:'AI 처음 만남', tag:'완전 처음',
        q:'"AI가 뭔진 모르겠는데 다들 쓰는 것 같아"',
        learn:['유튜브 알고리즘·번역기 — 이미 AI를 쓰고 있었다', 'ChatGPT가 뭔지 직접 들어가서 말 걸어보기', 'AI가 가끔 틀린다는 것 (환각)', 'AI로 물어보기 vs 검색하기 차이'],
        terms:[['AI','사람처럼 생각하는 척 하는 컴퓨터 프로그램'],['ChatGPT','OpenAI가 만든 대화형 AI. 말 걸면 답해줌'],['환각','AI가 모르는 걸 아는 척 꾸며내는 것. 믿으면 안 됨']],
        cases:[{who:'고2 · 문과', what:'ChatGPT에 "수행평가 주제 추천해줘" 넣었다가 너무 길어서 당황.', result:'AI가 틀릴 수 있다는 걸 직접 확인하고 나서야 믿고 쓰기 시작함'},{who:'중3 · 남학생', what:'"AI가 숙제 다 해주면 되는 거 아니야?" 생각했다가 선생님한테 걸림.', result:'AI 결과를 그대로 내면 안 된다는 걸 배움'}],
        mission:{time:'5분', task:'ChatGPT(chat.openai.com)에 접속해서 지금 궁금한 거 아무거나 물어보기.\n예: "광합성이 뭔지 쉽게 설명해줘"', check:'AI가 뭔가 답했으면 성공. 맞든 틀리든 OK.'},
        next:'ChatGPT에 질문을 3번 이상 해봤다', nextLv:'LV.1 →'},
      {lv:'LV.1', icon:'🔍', title:'제대로 물어보기', tag:'써봤지만 어색함',
        q:'"그냥 쓰긴 하는데, 내가 제대로 쓰는 건지 모르겠어"',
        learn:['AI한테 더 잘 물어보는 방법이 있다', '"역할"을 주면 답변이 달라진다', '같은 질문, 다르게 물어보고 비교하기', '수행평가·독서록·발표에 AI 활용하기'],
        terms:[['프롬프트','AI에게 하는 말. 어떻게 말하느냐가 결과를 바꿈'],['역할 주기','"너는 국어 선생님이야" 처럼 AI에게 역할을 부여하는 것'],['맥락','AI에게 미리 알려주는 배경 정보']],
        cases:[{who:'고3 · 이과', what:'"수학 문제 풀어줘"라고 했더니 중간 과정이 틀렸음.', result:'"풀이 과정도 설명해줘"를 붙이기 시작함. 직접 확인하는 습관 생김'},{who:'중2 · 여학생', what:'독서감상문 쓸 때 "줄거리만 써줘" 했다가 선생님이 알아채심.', result:'"이 책의 주제를 세 가지로 요약하고, 내가 가장 공감한 부분을 묻는 질문 3개 만들어줘"로 바꿈'}],
        mission:{time:'10분', task:'같은 질문 3가지 방식으로 바꿔서 ChatGPT에 넣어보기.\n① "광합성 설명해줘"\n② "초등학생한테 설명하듯이 광합성 설명해줘"\n③ "너는 생물 선생님이야. 광합성을 그림으로 그릴 수 있게 단계별로 설명해줘"', check:'3개 답변이 다르면 성공.'},
        next:'프롬프트 바꾸면 답이 달라진다는 걸 직접 느꼈다', nextLv:'LV.2 →'},
      {lv:'LV.2', icon:'⚙️', title:'공부에 연결하기', tag:'중고딩 심화',
        q:'"AI로 공부를 더 잘할 수 있을까?"',
        learn:['AI로 개념 설명·퀴즈·오답 분석하기', '내 노트를 AI에게 먹여서 개인 과외처럼 활용', 'AI에게 피드백 요청하는 법', '진로 탐색에 AI 활용하기'],
        terms:[['프롬프트 엔지니어링','AI에게 잘 부탁하는 기술'],['요약','긴 내용을 핵심만 뽑아 짧게 만드는 것'],['RAG','AI에게 내 자료를 먼저 읽히고 질문하는 방식']],
        cases:[{who:'고2 · 사회탐구', what:'"이 단원 내용으로 퀴즈 10개 만들어줘" → 직접 풀고 틀린 거 다시 설명 요청.', result:'단순 암기보다 이해가 빨라졌고 시험 성적도 올라감'},{who:'중3 · 진로 고민', what:'"나는 그림 그리는 걸 좋아하고 수학은 못해. 어떤 직업이 맞을까?"', result:'10개 직업 리스트 받고, 각 직업이 실제로 뭘 하는지 하나씩 물어보면서 좁혀나감'}],
        mission:{time:'15분', task:'오늘 수업 노트나 교과서 한 단원을 AI에게 붙여넣고:\n"이 내용으로 나한테 퀴즈 5개 내줘. 그리고 내가 답하면 채점해줘."\n→ 실제로 퀴즈 풀어보기', check:'퀴즈 5개 풀고 틀린 거 다시 설명 들었으면 성공.'},
        next:'AI를 공부에 실제로 써봤고 효과를 느꼈다', nextLv:null}
    ],
    career: [
      {lv:'LV.1', icon:'🔍', title:'프롬프트 제대로 쓰기', tag:'기초 탈출',
        q:'"그냥 쓰는 것 말고, 원하는 답을 뽑는 방법이 있어?"',
        learn:['역할+맥락+형식 세트로 주기', '자소서·발표자료 퀄리티 올리기', 'AI 답변 검증 체크리스트 만들기', '여러 AI 도구 비교해서 상황에 맞게 쓰기'],
        terms:[['프롬프트 엔지니어링','AI에게 잘 부탁하는 기술'],['컨텍스트','AI에게 알려주는 배경 정보. 많을수록 정확해짐'],['시스템 프롬프트','AI의 기본 역할을 미리 설정하는 지시문']],
        cases:[{who:'대학교 2학년 · 사회학과', what:'"이 내용 기반으로 나한테 퀴즈 내줘"를 시도.', result:'AI 기반 복습 루틴 완성. 시험 전날 루틴이 됨'},{who:'대학교 3학년 · 경영학과', what:'"전문가처럼 써줘"와 "HR 담당자처럼 써줘"의 결과가 완전히 다른 걸 발견.', result:'자소서 피드백 프롬프트 완성. 지원서 퀄리티 눈에 띄게 올라감'}],
        mission:{time:'10분', task:'관심 직무 채용공고 하나를 복사해서 ChatGPT에 붙여넣고:\n"이 공고에서 가장 중요한 역량 3가지만 뽑아줘.\n그리고 자소서에서 꼭 언급해야 할 키워드도 알려줘."', check:'역량 3개 + 키워드가 나왔으면 성공.'},
        next:'같은 목적의 프롬프트를 3가지 버전으로 만들어 비교했다', nextLv:'LV.2 →'},
      {lv:'LV.2', icon:'⚙️', title:'취준에 연결하기', tag:'실전 활용',
        q:'"자소서·직무분석·면접 준비에 AI를 제대로 쓰고 싶어"',
        learn:['채용공고 분석 → 자소서 키워드 추출', '자소서 피드백 사이클 (AI 피드백 → 수정 → 반복)', '면접 예상 질문 뽑고 연습하기', 'AI 없을 때 vs 있을 때 결과물 비교'],
        terms:[['JD','Job Description. 채용공고에서 직무 설명 부분'],['키워드 매핑','공고의 핵심 단어를 내 경험에 연결하는 것'],['AX','회사/업무 전체를 AI로 바꾸는 것 (AI Transformation)']],
        cases:[{who:'대학교 3학년 · 경영학과 · AX 직무 취준', what:'채용공고 10개를 AI에게 붙여넣고 공통 키워드를 뽑음.', result:'직무 분석 프레임워크 생김. 자소서 수정 5회 반복 후 서류 합격률 올라감'},{who:'졸업예정자 · 영어영문', what:'자소서 한 문단 붙여넣고 "HR 담당자 입장에서 약한 부분 짚어줘" 반복.', result:'애매한 표현이 줄고, 구체적인 수치와 결과 중심으로 바뀜'}],
        mission:{time:'15분', task:'내 자소서 한 문단을 ChatGPT에 붙여넣고:\n"이 자소서에서 애매하거나 구체적이지 않은 부분을 짚어줘.\n더 구체적으로 쓰려면 어떤 내용을 추가해야 할지도 알려줘."\n→ 피드백 받고 실제로 한 줄만 고쳐보기.', check:'고치기 전/후 비교해서 뭐가 달라졌는지 느꼈으면 성공.'},
        next:'AI 없이 했을 때와 있을 때 결과물 차이를 직접 느꼈다', nextLv:'LV.3 →'},
      {lv:'LV.3', icon:'🧭', title:'진로 방향 잡기', tag:'커리어 연결',
        q:'"AI 시대에 나는 어디로 가야 하지?"',
        learn:['AI 관련 직무 지형도 — 기획/개발/데이터/운영', 'AI가 대체 못하는 능력 — 문제 정의, 판단, 관계', 'LV.1~2 결과물을 포트폴리오로 만드는 법', '채용공고 5개 분석 → 공통 역량 뽑기'],
        terms:[['AX기획자','회사 업무를 AI로 어떻게 바꿀지 설계하는 사람'],['데이터 리터러시','숫자와 데이터를 읽고 해석하는 기초 능력'],['포트폴리오','내가 한 일을 보여주는 결과물 모음']],
        cases:[{who:'졸업예정자 · 경영정보학과', what:'"이걸로 뭘 할 수 있는 사람이에요?"라는 질문에 막혔음.', result:'"문제를 보는 눈"을 어필하는 방향으로 전환. 취업 성공'},{who:'대학교 3학년 · 컴퓨터공학과', what:'채용공고 20개 분석 → "AI를 업무에 연결하는 사람"을 더 많이 뽑는다는 걸 발견.', result:'기술 스택 중심 → 문제 해결 경험 중심으로 이력서 재구성'}],
        mission:{time:'20분', task:'관심 직무 채용공고 5개 찾아서 ChatGPT에 붙여넣고:\n"이 5개 공고에서 공통으로 요구하는 역량과 키워드를 뽑아줘.\nAI 관련 역량이 있다면 어떤 수준을 원하는지도 알려줘."\n→ 결과 보고 내 현재 수준과 비교해봐.', check:'공통 역량 목록이 나오고, 갖춘 것과 부족한 것 구분했으면 성공.'},
        next:'내 커리어 방향과 다음 할 일이 하나 이상 구체적으로 생겼다', nextLv:null}
    ],
    work: [
      {lv:'LV.1', icon:'🔍', title:'업무 보조로 쓰기', tag:'AI 첫 도입',
        q:'"업무에 AI를 써보고 싶은데 어떻게 시작하지?"',
        learn:['보고서·이메일·회의록 AI로 다듬기', '반복 업무에서 AI가 도움 되는 부분 찾기', 'AI 답변 검증 — 그대로 쓰면 안 되는 이유', '팀에 AI 쓴다고 말하기 전에 먼저 해볼 것들'],
        terms:[['생성형 AI','텍스트·이미지·코드 등을 새로 만들어내는 AI'],['프롬프트','AI에게 하는 지시문. 잘 쓸수록 결과가 달라짐'],['할루시네이션','AI가 없는 사실을 있다고 만들어내는 현상. 검증 필수']],
        cases:[{who:'마케팅팀 대리 · 5년차', what:'주간 보고서 초안을 AI에게 시켰더니 방향은 맞는데 수치가 틀렸음.', result:'"수치는 내가 넣을게, 구조랑 문장만 다듬어줘"로 역할 나눔. 작성 시간 40% 단축'},{who:'인사팀 과장 · 중년', what:'"AI가 뭔지 모르겠어서 무서웠는데" 이메일 다듬기부터 시작.', result:'일주일 만에 하루 30분 절약. 지금은 채용공고 초안까지 AI로 작성'}],
        mission:{time:'10분', task:'지금 하고 있는 업무에서 반복적인 것 하나를 골라서\nChatGPT에게 "이걸 더 빠르게 할 수 있는 방법 있어?"라고 물어보기.\n예: 회의록 정리, 메일 작성, 보고서 목차 잡기', check:'AI가 제안한 방법 중 1개라도 실제로 써봤으면 성공.'},
        next:'업무에서 AI가 실제로 도움 된 순간을 1번 이상 경험했다', nextLv:'LV.2 →'},
      {lv:'LV.2', icon:'⚙️', title:'업무 흐름에 연결', tag:'실전 활용',
        q:'"AI를 그냥 쓰는 게 아니라, 업무 흐름에 제대로 연결하고 싶어"',
        learn:['반복 업무 자동화 가능성 진단', '노코드 도구로 간단한 자동화 만들기 (Make, Zapier)', 'AI가 해야 할 일 vs 사람이 해야 할 일 구분하기', '팀에 AI 도입할 때 설득하는 법'],
        terms:[['자동화','내가 안 해도 알아서 돌아가게 만들기'],['노코드','코딩 없이 도구를 연결해서 자동화 만드는 것'],['워크플로우','반복 작업을 순서대로 흐르게 만든 것']],
        cases:[{who:'기획팀 차장 · 15년차', what:'주간 데이터 취합 → 보고서 작성이 매주 3시간.', result:'Make로 자동 취합 → AI 초안 생성 흐름 만들어 1시간으로 단축'},{who:'스타트업 COO', what:'"우리 팀이 AI를 도입해야 하는데 뭐부터 해야 하지?"', result:'ddugi로 업무 문제 정의 → AI 필요한 곳과 아닌 곳 구분 → 우선순위 3개 도출'}],
        mission:{time:'20분', task:'지금 팀에서 가장 반복적인 업무 하나를 골라서\nddugi 씨앗 정의서(01번)에 직접 써보기.\n"지금 어떻게 하고 있어? 뭐가 불편해? AI로 뭐가 달라지면 좋겠어?"', check:'씨앗 이름 + 핵심 문제 한 줄 완성했으면 성공.', link:true},
        next:'내가 설계한 개선안이 실제로 한 번 이상 팀에서 쓰였다', nextLv:'LV.3 →'},
      {lv:'LV.3', icon:'🛠️', title:'AX 설계하기', tag:'AX 기획',
        q:'"팀·부서 단위로 AI를 제대로 도입하고 싶어"',
        learn:['AX 과제 탐색·설계 프로세스 (ddugi 전체 흐름)', 'AI 필요성 진단 — 억지로 AI 붙이지 않기', 'AI Slop 탐지 — 단순 자동화를 AI로 포장하면 안 되는 이유', '효과 측정 방법 설계'],
        terms:[['AX','AI Transformation. 업무 자체를 AI로 재설계하는 것'],['AI Slop','필요 없는 곳에 AI를 붙이거나 검증 없이 결과물을 쓰는 것'],['PoC','Proof of Concept. 제일 작은 버전으로 먼저 검증하는 것']],
        cases:[{who:'IT기업 PM · 8년차', what:'"AI 도입하자"는 경영진 지시 → 어디서 시작해야 할지 몰랐음.', result:'ddugi로 5개 업무 후보 탐색 → AI 필요한 것 2개·불필요한 것 3개 구분 → 우선순위 명확해짐'},{who:'제조업 팀장 · 20년차', what:'보고서 AI 자동 생성 만들었는데 직원들이 안 씀.', result:'사용자 인터뷰 → "결과물 믿을 수가 없어요" → Human-in-the-loop 구조로 재설계'}],
        mission:{time:'30분', task:'ddugi 씨앗 찾기(00번)에서 팀의 업무를 자유롭게 설명하고\nAI가 찾아주는 개선 후보 2~3개 받아보기.\n→ "적합" 판정 받은 것만 다음 단계로', check:'AI 적합·부적합 판정 결과를 보고 팀에 공유할 수 있겠다 싶으면 성공.', link:true},
        next:'AX 과제 정의서를 완성하고 팀원과 공유했다', nextLv:null}
    ]
  };

  function tHtml(){
    return '<div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap;">' +
      tabs.map(t=>{
        const a = window._curriculumTab3===t.id;
        return '<button type="button" onclick="curricTab3(\''+t.id+'\')" style="padding:10px 16px;border-radius:10px;border:2px solid '+(a?'var(--blueprint)':'var(--line)')+';background:'+(a?'var(--blueprint-soft)':'var(--panel)')+';color:'+(a?'var(--blueprint)':'var(--ink-soft)')+';font-weight:'+(a?700:400)+';font-size:13px;cursor:pointer;text-align:left;line-height:1.3;">'+
          t.label+'<br><span style="font-size:11px;opacity:.65;">'+t.desc+'</span>'+
        '</button>';
      }).join('')+'</div>';
  }

  function fHtml(list){
    return '<div style="display:flex;align-items:center;gap:0;overflow-x:auto;padding-bottom:4px;margin-bottom:16px;">' +
      list.map((l,i)=>{
        const a=i===(window._curriculumIdx3||0);
        return '<button type="button" onclick="curricSelect3('+i+')" style="background:none;border:none;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:4px;padding:0;">'+
          '<div style="width:52px;height:52px;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;border:2px solid '+(a?'var(--blueprint)':'var(--line)')+';background:'+(a?'var(--blueprint-soft)':'var(--panel)')+';transition:all .15s;">'+
            '<span style="font-size:9px;font-weight:700;color:'+(a?'var(--blueprint)':'var(--placeholder)')+'">'+l.lv+'</span>'+
            '<span style="font-size:17px;">'+l.icon+'</span>'+
          '</div>'+
          '<span style="font-size:10px;color:'+(a?'var(--blueprint)':'var(--ink-soft)')+';font-weight:'+(a?700:400)+';text-align:center;max-width:60px;line-height:1.3;">'+l.title+'</span>'+
        '</button>'+(i<list.length-1?'<div style="width:28px;height:2px;background:var(--line);margin-bottom:20px;flex-shrink:0;"></div>':'');
      }).join('')+'</div>';
  }

  function cHtml(l,i){
    return '<div style="border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;">'+
      '<div style="padding:16px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;">'+
        '<div style="width:44px;height:44px;border-radius:10px;background:var(--blueprint-soft);display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;">'+
          '<span style="font-size:9px;color:var(--blueprint);font-weight:700;">'+l.lv+'</span><span style="font-size:18px;">'+l.icon+'</span></div>'+
        '<div style="flex:1;"><div style="font-size:16px;font-weight:700;color:var(--ink);">'+l.title+'</div>'+
          '<div style="font-size:12px;color:var(--ink-soft);font-style:italic;margin-top:2px;">'+l.q+'</div></div>'+
        '<span style="font-size:11px;padding:3px 10px;border-radius:20px;border:1px solid var(--line);color:var(--ink-soft);white-space:nowrap;flex-shrink:0;">'+l.tag+'</span>'+
      '</div>'+
      '<div style="display:grid;grid-template-columns:1fr 1fr;">'+
        '<div style="padding:16px 20px;border-bottom:1px solid var(--line);border-right:1px solid var(--line);">'+
          '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--ink-soft);margin-bottom:8px;">배우는 것</div>'+
          l.learn.map(t=>'<div style="font-size:12px;line-height:1.7;color:var(--ink);padding-left:12px;position:relative;"><span style="position:absolute;left:3px;color:var(--ink-soft);">·</span>'+t+'</div>').join('')+
        '</div>'+
        '<div style="padding:16px 20px;border-bottom:1px solid var(--line);">'+
          '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--ink-soft);margin-bottom:8px;">용어 풀어쓰기</div>'+
          l.terms.map(([k,v])=>'<div style="font-size:12px;line-height:1.7;color:var(--ink);padding-left:12px;position:relative;"><span style="position:absolute;left:3px;color:var(--ink-soft);">·</span><b>'+k+'</b> = '+v+'</div>').join('')+
        '</div>'+
      '</div>'+
      '<div style="padding:16px 20px;border-bottom:1px solid var(--line);">'+
        '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--ink-soft);margin-bottom:10px;">실제 사례</div>'+
        l.cases.map(c=>'<div style="background:var(--paper);border:1px solid var(--line-soft);border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:12px;line-height:1.6;">'+
          '<div style="font-size:10px;font-weight:700;color:var(--ink-soft);margin-bottom:3px;">'+c.who+'</div>'+
          '<div style="color:var(--ink);">'+c.what+'</div>'+
          '<div style="margin-top:4px;font-size:11px;">→ <b style="color:var(--blueprint);">'+c.result+'</b></div></div>').join('')+
      '</div>'+
      (l.mission ?
      '<div style="padding:16px 20px;border-bottom:1px solid var(--line);background:var(--blueprint-soft);">'+
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'+
          '<span style="font-size:13px;">🎯</span>'+
          '<span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--blueprint);">이번 미션</span>'+
          '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:var(--blueprint);color:#fff;font-weight:600;">⏱ '+l.mission.time+'</span>'+
        '</div>'+
        '<div style="font-size:13px;color:var(--ink);line-height:1.8;white-space:pre-line;margin-bottom:10px;">'+l.mission.task+'</div>'+
        '<div style="font-size:12px;color:var(--blueprint);font-weight:600;">✅ 완료 기준: '+l.mission.check+'</div>'+
        (l.mission.link ? '<div style="margin-top:10px;"><button type="button" onclick="curricGoto(\'s1\')" style="font-size:12px;padding:7px 16px;border-radius:8px;background:var(--blueprint);color:#fff;border:none;cursor:pointer;font-weight:600;">→ ddugi에서 씨앗 심으러 가기</button></div>' : '')+
      '</div>' : '')+
      '<div style="padding:12px 20px;background:var(--panel);display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'+
        '<span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--ink-soft);">'+(l.nextLv?'다음 레벨 조건':'이후')+'</span>'+
        '<span style="font-size:12px;color:var(--ink);flex:1;">'+l.next+'</span>'+
        (l.nextLv?'<button type="button" onclick="curricSelect3('+(i+1)+')" style="font-size:12px;padding:5px 14px;border-radius:6px;border:1px solid var(--line);background:transparent;color:var(--blueprint);font-weight:600;cursor:pointer;">'+l.nextLv+'</button>':'')+
      '</div></div>';
  }

  window.curricTab3 = function(id){
    window._curriculumTab3=id; window._curriculumIdx3=0;
    const el=document.getElementById('curricWrap3'); if(el) el.innerHTML=buildC3();
  };
  window.curricSelect3 = function(idx){
    window._curriculumIdx3=idx;
    const el=document.getElementById('curricWrap3'); if(el) el.innerHTML=buildC3();
  };
  function buildC3(){
    const tab=window._curriculumTab3||'teen', list=levels[tab];
    const idx=Math.min(window._curriculumIdx3||0, list.length-1);
    window._curriculumIdx3=idx;
    return tHtml()+fHtml(list)+cHtml(list[idx],idx);
  }
  return '<div id="curricWrap3">'+buildC3()+'</div>';
}
