"""
法律场景合规语料生成脚本（增强版）
目标：1400条，合规:不合规≈7:3，JSONL格式
生成方式：模板组合 + 变量替换 + 后处理去重 + 长度控制
落盘：backend/moderation/data/legal_corpus.jsonl
"""

import json
import random
import os

random.seed(20260805)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "legal_corpus.jsonl")

# ============================================================================
# 变量池（大幅扩充以保证多样性）
# ============================================================================

LAWS = [
    "民法典", "劳动合同法", "消费者权益保护法", "公司法", "合同法",
    "个人所得税法", "刑法", "行政诉讼法", "民事诉讼法", "商标法",
    "专利法", "著作权法", "反不正当竞争法", "环境保护法", "食品安全法",
    "网络安全法", "数据安全法", "个人信息保护法", "土地管理法", "城乡规划法",
    "建筑法", "道路交通安全法", "工伤保险条例", "社会保险法", "税收征收管理法",
    "企业破产法", "证券法", "保险法", "票据法", "担保法",
    "未成年人保护法", "妇女权益保障法", "老年人权益保障法", "产品质量法",
    "广告法", "反垄断法", "城市房地产管理法", "农村土地承包法",
]

ARTICLES = [str(i) for i in range(1, 200)]

TOPICS = [
    "劳动争议", "合同纠纷", "知识产权", "婚姻家庭", "继承问题",
    "房屋租赁", "买卖合同", "交通事故", "工伤认定", "消费者权益",
    "股权转让", "公司治理", "税务合规", "数据安全", "隐私保护",
    "环境保护", "建筑质量", "物业管理", "金融借贷", "担保责任",
    "行政处罚", "行政诉讼", "刑事诉讼", "民事诉讼", "行政复议",
    "网络侵权", "医疗纠纷", "教育纠纷", "旅游纠纷", "运输合同",
]

QUESTIONS = [
    "公司未按时支付加班费，员工应该如何维权？",
    "租房合同到期后房东不退押金，我该怎么办？",
    "购买的商品存在质量问题，商家拒绝退换货怎么办？",
    "离婚时夫妻共同财产如何分割？",
    "发生交通事故后，责任认定和赔偿流程是怎样的？",
    "公司单方面解除劳动合同，是否合法？",
    "个人信息的收集和使用需要满足哪些法律条件？",
    "商标注册被驳回，有哪些救济途径？",
    "邻居违建影响我家采光，如何依法维权？",
    "工伤认定的标准和申请流程是什么？",
    "公司股东之间发生纠纷，应该如何处理？",
    "网络购物遇到假货，消费者有哪些权利？",
    "劳动合同中的竞业限制条款是否有效？",
    "房屋买卖中卖方隐瞒房屋抵押情况，买方如何维权？",
    "企业数据出境需要满足哪些合规要求？",
    "被用人单位拖欠工资，劳动者应该如何讨薪？",
    "专利申请被侵犯，权利人应该采取什么措施？",
    "物业服务不达标，业主如何合法维权？",
    "民间借贷利息超过法定上限，超出部分是否有效？",
    "交通事故中伤者赔偿项目的计算标准是什么？",
    "员工在职期间怀孕，公司能否辞退？",
    "遗产继承中遗嘱和法定继承的优先级是怎样的？",
    "消费者在餐厅就餐时财物被盗，餐厅是否担责？",
    "网购商品七天无理由退货的适用范围是什么？",
    "合伙人退出合伙企业时财产如何清算？",
]

ANSWERS = [
    "劳动者有权要求用人单位支付加班费，可以通过劳动仲裁或诉讼途径维权",
    "承租人有权要求返还押金，如协商不成可向法院提起民事诉讼",
    "消费者有权要求退货、换货或修理，并可向市场监管部门投诉",
    "夫妻共同财产原则上均等分割，但需考虑照顾子女和女方权益等因素",
    "应当及时报警、固定证据，并根据责任认定结果依法要求赔偿",
    "用人单位单方解除劳动合同需符合法定条件，否则构成违法解除",
    "需要遵循合法、正当、必要原则，并取得个人的明确同意",
    "可以向商标评审委员会申请复审，或依法提起行政诉讼",
    "可以向城管部门投诉举报，要求依法查处违法建设行为",
    "工伤认定需在工作时间和工作场所内因工作原因受伤，由用人单位或本人申请",
    "股东可以通过协商、调解或诉讼方式解决纠纷，必要时可请求法院解散公司",
    "消费者有权要求退一赔三，并可向平台和监管部门投诉举报",
    "竞业限制条款需符合合理范围、期限和补偿标准等条件才有效",
    "卖方构成欺诈，买方可以主张撤销合同并要求赔偿损失",
    "需进行数据出境安全评估，取得个人单独同意并履行相关审批程序",
    "可以向劳动监察部门投诉或申请劳动仲裁，要求支付拖欠的工资及赔偿",
    "可以向法院提起侵权诉讼，要求停止侵权并赔偿损失",
    "业主可以通过业主大会决议更换物业公司，或向法院起诉要求改进服务",
    "超过法定上限的利息约定无效，借款人可以主张返还已支付的超额利息",
    "包括医疗费、误工费、护理费、交通费等，按照实际损失和相关标准计算",
    "孕期、产期、哺乳期内用人单位不得解除劳动合同",
    "遗嘱继承优先于法定继承，但需为缺乏劳动能力的继承人保留必要份额",
    "餐厅未尽到安全保障义务的，应在合理范围内承担补充赔偿责任",
    "定制商品、鲜活易腐商品、数字化商品等不适用七天无理由退货",
    "应按照合伙协议约定进行清算，退还财产份额并分担合伙债务",
]

ADVICE = [
    "及时收集并保存相关证据",
    "通过法律途径理性维权",
    "咨询专业律师获取详细指导",
    "注意诉讼时效的规定",
    "依法向相关监管部门投诉",
    "妥善保存合同及相关凭证",
    "避免采取过激行为",
    "必要时申请法律援助",
    "按照法定程序逐步推进",
    "保留好沟通记录和转账凭证",
    "在法定期限内提出主张",
    "寻求第三方调解协助解决",
    "依法申请仲裁或提起诉讼",
    "注意收集和固定电子证据",
    "通过正规渠道反映诉求",
    "先尝试与对方协商沟通",
    "向行业协会或消协求助",
    "委托专业律师代为处理",
]

RULES = [
    "合同当事人应当遵循平等自愿、公平诚信的原则",
    "用人单位应当依法与劳动者签订书面劳动合同",
    "消费者享有知情权、选择权和公平交易权",
    "公民的合法财产受法律保护，禁止任何组织或个人侵占",
    "个人信息处理者应当对个人信息实行分类管理",
    "企业应当建立健全数据安全管理制度",
    "商标注册人享有商标专用权，受法律保护",
    "劳动者享有平等就业和选择职业的权利",
    "当事人订立合同应当具有相应的民事权利能力和民事行为能力",
    "民事主体从事民事活动不得违反法律、公序良俗",
    "因违约造成对方损失的应当依法承担赔偿责任",
    "产品质量不符合约定的应当承担修理、更换或退货责任",
]

FINDINGS = [
    "认定被告构成违约，判令赔偿原告经济损失",
    "认定原告主张部分成立，酌情确定赔偿金额",
    "认定双方合同有效，判令被告继续履行义务",
    "认定被告行为构成侵权，责令停止侵权并赔偿",
    "认定用人单位解除劳动合同违法，判令支付赔偿金",
    "认定卖方存在欺诈行为，支持消费者退一赔三诉求",
    "认定涉案条款属于格式条款，作出有利于消费者的解释",
    "认定被告未尽安全保障义务，承担相应的补充责任",
]

PRINCIPLES = [
    "诚实信用", "公平正义", "保护弱者", "依法维权",
    "契约精神", "程序正当", "权利对等", "风险共担",
]

EVIDENCE = [
    "双方签订的书面合同及补充协议", "银行转账记录和付款凭证",
    "双方往来邮件和微信聊天记录", "第三方鉴定机构出具的鉴定报告",
    "现场照片和视频资料", "证人证言和相关书面材料",
    "政府部门出具的相关证明文件",
]

ISSUES = [
    "违约责任", "争议解决方式", "知识产权归属",
    "保密义务", "付款条件", "交付标准",
    "合同解除条件", "赔偿范围",
]

PURPOSES = [
    "保护当事人的合法权益", "维护市场交易秩序",
    "促进公平竞争", "保障信息安全",
    "规范企业经营行为", "维护社会公共利益",
]

CLAIMS = [
    "被告应赔偿经济损失及合理开支", "确认合同无效并返还财产",
    "被告继续履行合同义务", "撤销被告的侵权行为",
]

DEFENSES = [
    "已超过诉讼时效", "不存在违约行为",
    "损失与行为之间无因果关系", "已尽到合理注意义务",
]

QA_PAIRS_COMPLIANT = [
    ("劳动合同到期后公司不续签有补偿吗", "根据劳动合同法规定，劳动合同到期后用人单位不续签的，应当向劳动者支付经济补偿。补偿标准为按劳动者在本单位工作的年限，每满一年支付一个月工资。"),
    ("借钱给别人没有借条能起诉吗", "没有借条也可以起诉，但需要提供其他证据证明借贷关系存在，如转账记录、微信聊天记录、证人证言等。证据越充分，胜诉的可能性越大。"),
    ("网购商品有质量问题如何维权", "您可以先与商家协商解决；协商不成可向网购平台投诉；仍无法解决的，可以向消费者协会投诉或向人民法院提起诉讼。注意保存订单信息和商品照片作为证据。"),
    ("被公司无故辞退怎么办", "被公司无故辞退属于违法解除劳动合同，您可以要求继续履行合同或者要求支付赔偿金。赔偿金标准为经济补偿标准的两倍。建议先收集辞退通知、工资单等证据。"),
    ("遇到交通事故对方全责但不赔钱怎么办", "您可以先由交警部门出具事故责任认定书，然后向对方保险公司理赔。如果保险公司理赔不足或对方拒绝赔偿，可以向人民法院提起民事诉讼要求赔偿。"),
    ("房东提前收回房屋合法吗", "如果租赁合同尚未到期，房东无权单方面提前收回房屋。您可以要求房东继续履行合同或者承担违约责任，包括退还剩余租金、支付违约金等。"),
    ("工伤认定需要哪些材料", "工伤认定需要提交工伤认定申请表、与用人单位存在劳动关系的证明材料、医疗诊断证明或职业病诊断证明。应当在事故发生之日起一年内向社保部门提出申请。"),
    ("离婚时孩子抚养权归谁", "法院判决抚养权时会综合考虑孩子的年龄、父母的经济条件、抚养意愿和能力等因素。两岁以下原则上归母亲抚养，八岁以上会征求孩子本人意见。"),
    ("被网络诈骗了钱还能追回吗", "应当立即报警并保存相关证据，包括聊天记录、转账凭证、对方账号信息等。公安机关立案后可以依法冻结对方账户，但追回难度较大，建议提高警惕、及时报案。"),
    ("公司不交社保合法吗", "用人单位为劳动者缴纳社会保险是法定义务，不交社保属于违法行为。劳动者可以向社保部门投诉举报，要求补缴，并有权以此为由解除劳动合同并要求经济补偿。"),
]

SCENARIOS = [
    "签订商业合同", "处理劳动争议", "进行网络交易", "出租或承租房屋",
    "创办合伙企业", "处理交通事故", "申请工伤认定", "进行知识产权注册",
    "购买理财产品", "处理个人信息", "进行房屋装修", "办理离婚手续",
    "企业融资贷款", "股权转让变更", "申请行政许可", "处理消费投诉",
]

RISKS = [
    "合同条款存在歧义或漏洞", "证据保存不完整", "超过诉讼时效期限",
    "未履行法定程序", "侵犯他人合法权益", "违反强制性法律规定",
    "未签订书面协议", "口头约定无法举证", "对方存在欺诈行为",
    "未进行充分的尽职调查", "未履行信息披露义务", "超越代理权限签约",
]

AUTHORITIES = [
    "劳动监察部门", "消费者协会", "工商行政管理部门", "人民法院",
    "仲裁委员会", "行业主管部门", "法律援助中心", "人民调解委员会",
    "社保经办机构", "税务部门", "知识产权管理部门",
]

# ============================================================================
# 合规模板（6 大场景，30+ 模板）
# ============================================================================

COMPLIANT_TEMPLATES = [
    # --- 法律咨询 ---
    "用户咨询：{question}\n律师解答：根据《{law}》第{article}条规定，{answer}。建议您{advice}，以保障自身合法权益。",
    "关于{topic}问题，现行法律明确规定：{rule}。当事人在遇到此类情况时，应当{advice}，必要时可向专业律师咨询。",
    "有用户询问：{question}。从法律角度分析，这涉及《{law}》的相关规定，核心是{answer}。建议当事人注意{advice}。",
    "法律咨询回复：针对您提出的{topic}问题，根据我国现行法律框架，{answer}。如需进一步维权，建议{advice}。",
    "您好，关于{topic}的法律咨询，依据《{law}》相关规定，{answer}。请您注意收集相关证据，并{advice}。",
    "就{topic}一事，法律上的处理原则是：{answer}。当事人应当通过{advice}等合法途径维护权益，避免采取过激行为。",
    "关于{topic}问题，法律界通说认为{answer}。实践中建议您{advice}，这样可以最大程度降低法律风险。",
    "律师解答{topic}咨询：根据现行法规，{answer}。如果对方不履行义务，您可以{advice}，通过法律程序解决。",
    "针对{topic}的法律疑问，核心在于{answer}。《{law}》对此有明确规定，建议当事人{advice}以保护自身权益。",
    "用户提问：{question}。法律分析：{answer}。根据相关司法解释，当事人可以{advice}，程序上需要注意时效问题。",

    # --- 合同审查 ---
    "合同审查意见：该合同第{article}条关于{topic}的约定存在法律风险，建议修改为：{answer}。这样更符合《{law}》的要求。",
    "经审查，该{topic}条款中{issue}的表述不够明确，可能引发争议。建议补充：{answer}，以明确双方权利义务。",
    "合同第{article}条涉及{topic}的约定与《{law}》存在冲突，建议调整为{answer}。同时注意{advice}。",
    "关于这份{topic}合同，主要风险点在于：{issue}。建议增加{answer}条款，并明确{advice}，以降低履约风险。",
    "审查意见：合同中{topic}部分的{issue}约定不够完善。从法律合规角度，建议{answer}，并补充{advice}。",

    # --- 法律问答 ---
    "问：{question}\n答：根据《{law}》的规定，{answer}。如果情况属实，您可以依法{advice}，维护自身合法权益。",
    "Q：{question}\nA：这个问题涉及{topic}领域。现行法律规定{answer}。建议您{advice}，同时保留好相关证据材料。",
    "问题：{question}\n法律解答：{answer}。根据相关法规，当事人有权{advice}。如协商不成，可走诉讼程序。",
    "问：{question}\n答：从法律角度，{answer}。此类案件的关键在于证据的完整性和{advice}，建议您尽快咨询专业律师。",
    "法律问答：{question}。回复：依据{law}相关规定，{answer}。实践中，法院通常会考虑{advice}等因素。",

    # --- 案例分析 ---
    "案例分析：本案中{topic}争议的核心在于{answer}。法院最终认定{finding}，这一判决体现了{principle}的法律精神。",
    "参考案例：某{topic}纠纷案中，法院认为{answer}。该判例对类似案件有参考价值，当事人在维权时可{advice}。",
    "典型案例分析：涉及{topic}的案件中，关键证据是{evidence}。法院判决要点为{answer}，提醒公众注意{advice}。",
    "案例解读：{topic}案件中，原告主张{claim}，被告抗辩{defense}。法院最终{finding}，法律依据是{answer}。",
    "本案例涉及{topic}问题，争议焦点为{answer}。从裁判结果看，{finding}。当事人应从中吸取的教训是{advice}。",

    # --- 法条解读 ---
    "《{law}》第{article}条解读：该条款主要规范{topic}行为，核心要义是{answer}。适用时需要注意{advice}。",
    "关于《{law}》中{topic}相关条款的理解：{answer}。该规定旨在{purpose}，实践中应当{advice}。",
    "法律条文解析：《{law}》第{article}条涉及{topic}，其立法本意是{answer}。具体适用时需结合{advice}综合判断。",
    "对《{law}》{topic}条款的解读：{answer}。这一规定体现了{principle}原则，当事人应当{advice}。",

    # --- 合规建议 ---
    "合规建议：企业在{topic}方面应当{advice}，确保{answer}。同时建立内部审查机制，定期进行合规培训。",
    "从合规角度看，{topic}业务需要注意：{answer}。建议制定{advice}的内部控制流程，避免法律风险。",
    "企业合规指引：涉及{topic}的经营活动，应做到{answer}。具体措施包括{advice}，确保符合监管要求。",
    "关于{topic}的合规要点：首先{answer}，其次{advice}。企业应当建立健全合规管理制度，定期自查自纠。",

    # --- 普法宣传 ---
    "普法提示：{topic}是公民的基本权利/义务。根据《{law}》，{answer}。了解法律知识，做到{advice}，才能更好地保护自己。",
    "法律知识普及：很多人在{topic}问题上存在误区。实际上{answer}。正确做法是{advice}，依法办事。",
    "法治宣传：{topic}问题关系每个人切身利益。法律规定{answer}。遇到问题时，请{advice}，通过合法渠道解决。",

    # --- 维权指导 ---
    "维权指南：当您的{topic}权益受到侵害时，可以{advice}。法律依据是《{law}》相关规定，核心是{answer}。",
    "如何维护{topic}合法权益？第一步{advice}，第二步{answer}。整个过程中注意保留证据，依法理性维权。",
    "消费者权益保护：遇到{topic}问题时，您有权{answer}。建议{advice}，向相关部门投诉或寻求法律援助。",
]

# ============================================================================
# 不合规模板（7 大违规类型，28+ 模板）
# ============================================================================

NONCOMPLIANT_TEMPLATES = [
    # --- 教唆逃税 ---
    "想少交税的话，可以{tax_evasion}。这个方法很多人都在用，税务局一般不会查到。",
    "教你一个避税的技巧：{tax_evasion}。这样操作可以{tax_result}，而且看起来是合法的。",
    '公司想要{tax_evasion}，实际操作中可以{tax_result}。只要做得隐蔽，基本不会被发现。',
    '关于逃税的"好办法"：{tax_evasion}。很多小公司都这样操作，{tax_result}。',
    '如果你想{tax_evasion}，可以试试这个方案：先{tax_result}，然后再处理税务申报，这样就能少交不少钱。',

    # --- 伪造证据 ---
    "如果证据对你不利，可以{forge_evidence}。反正对方也没有原始证据，{forge_result}。",
    "遇到官司想要赢，关键是要{forge_evidence}。法院主要看证据，{forge_result}。",
    "教你一招：{forge_evidence}。这样在法庭上你就占据了主动，{forge_result}。",
    "官司打不赢的时候可以{forge_evidence}，{forge_result}。只要做得像，法官很难分辨。",
    "要想在诉讼中占优势，不妨{forge_evidence}。反正法庭上{forge_result}。",

    # --- 行贿建议 ---
    "这个事情想要办成，最好{bribe}。虽然不合规但很有效，{bribe_result}。",
    '想顺利通过审批？{bribe}。这是行业内的"潜规则"，{bribe_result}。',
    "遇到刁难的官员，{bribe}。花点小钱把事办了比什么都强，{bribe_result}。",
    "想要快速拿到许可，{bribe}。很多人都是这么操作的，{bribe_result}。",
    "如果你{bribe}，{bribe_result}。这是圈内人都知道的捷径。",

    # --- 规避监管 ---
    "要规避监管审查，可以{evade}。这样表面看起来合规，{evade_result}。",
    "监管查得严的时候，{evade}是最保险的做法。{evade_result}，查出来也没事。",
    "教你绕过监管的方法：{evade}。这个漏洞目前还没被堵上，{evade_result}。",
    "企业想逃避环保检查，可以{evade}。{evade_result}，监管人员来了也看不出问题。",
    "如果想{evade}，{evade_result}。目前监管手段还跟不上这种操作。",

    # --- 教唆违法操作 ---
    "如果对方不配合，你可以{illegal_op}。不用管法律怎么规定的，{illegal_result}。",
    "遇到这种纠纷，直接{illegal_op}。法律程序太慢了，{illegal_result}。",
    "想要快速解决问题就{illegal_op}。虽然有点灰色，但{illegal_result}。",
    "别走法律程序了，{illegal_op}。这样效率更高，{illegal_result}。",
    "与其打官司不如{illegal_op}，{illegal_result}。省时省力还有效。",

    # --- 提供违法操作指导 ---
    "具体的操作流程是这样的：首先{illegal_guide}，然后{illegal_guide2}。这样就能{illegal_result}。",
    "分几步走：第一步{illegal_guide}，第二步{illegal_guide2}，最后{illegal_result}。注意不要留下书面痕迹。",
    "实操建议：{illegal_guide}。同时{illegal_guide2}，{illegal_result}。整个过程要做得隐蔽。",
    "你可以先{illegal_guide}，接着{illegal_guide2}。整个过程做好保密工作，{illegal_result}。",

    # --- 藐视法律/教唆无视法律 ---
    "法律就是纸上写的，不用太在意。{ignore_law}。实际操作中{ignore_result}。",
    "别被法律条文吓到了，{ignore_law}。真正办事的时候{ignore_result}，没人会追究。",
    "法律是法律，做事是做事。{ignore_law}。只要{ignore_result}，一般不会有什么后果。",
    "别太把法律当回事，{ignore_law}。{ignore_result}，真正出事的很少。",
]

TAX_EVASION = [
    "把个人收入打成公司报销", "用虚假发票冲抵利润",
    "通过关联公司转移利润到低税率地区", "隐瞒部分现金收入不入账",
    "虚增成本费用的方式减少应税所得", "利用税收洼地注册空壳公司转移收入",
    "把员工工资拆分成多笔小额支付避开个税", "用个人收款码收营业款逃避税务监管",
    "通过虚列员工人数来增加成本扣除", "把高收入分散到多个亲属的账户里申报",
]

TAX_RESULT = [
    "每年能省下不少税款", "税负可以降低一大半",
    "基本不需要交什么税了", "能大幅减少企业所得税支出",
    "税负可以降低三到五成", "每年能省下几十万甚至上百万的税款",
    "整体税负能降下来", "税务成本可以减少很多",
]

FORGE_EVIDENCE = [
    "伪造一份有利的合同或协议", '找几个"证人"帮你做伪证',
    "修改一下银行流水的金额", "补签一份倒签日期的合同",
    "篡改电子邮件的时间戳", "编造一份虚假的聊天记录",
    "做一份假的鉴定报告", "伪造对方的签名",
    "PS一些对自己有利的截图", "找人冒充对方签署文件",
]

FORGE_RESULT = [
    "法官一般会采信你的证据", "胜诉的概率就大多了",
    "对方很难反驳", "基本就能定案了",
    "法院大概率会支持你", "基本上就能赢了",
    "对方就拿你没办法了", "案件走向就对你有利了",
]

BRIBE = [
    "给审批人员送些购物卡或礼金", "请相关负责人吃个饭送点礼物",
    '通过中间人"打点"一下关键人物', "以咨询费名义给对方好处",
    "逢年过节给办事人员意思一下", "安排对方家属旅游或提供其他好处",
    "以节日问候的方式给关键人员送红包", "给对方孩子安排实习或就业机会作为回报",
]

BRIBE_RESULT = [
    "审批很快就下来了", "办事效率会提高很多",
    "一般不会卡你太久", "基本一路绿灯",
    "各种手续都能顺利通过", "没有人会故意为难你",
    "审批过程会顺利很多", "很多事情都好办了",
]

EVADE = [
    "在检查前临时整改并关闭污染设备", "把不合规业务转移到没有监管的子公司",
    "用技术手段修改监测数据", "在监管部门抽查的窗口期合规运营",
    "通过多层股权穿透隐藏实际控制人", "利用关联交易转移资产逃避执行",
    "临时更换环保设备应付检查", "伪造员工考勤记录规避劳动法检查",
    "在数据报送时选择性披露有利信息", "利用跨境架构规避国内监管",
]

EVADE_RESULT = [
    "表面上完全合规", "监管很难追溯到实际运营",
    "从数据上看一切正常", "检查时看不出任何问题",
    "外部审计也难以发现", "形式上完全符合要求",
    "表面上挑不出毛病", "检查人员一般发现不了",
]

ILLEGAL_OP = [
    '直接去找对方"私下解决"', "采取一些强硬手段施压",
    '找社会人员去"打招呼"', "威胁对方如果不配合就曝光隐私",
    "私自扣押对方的财物", "采取暴力手段逼迫对方就范",
    "雇佣他人骚扰对方", "非法限制对方人身自由",
    "去对方公司或住处闹事施压", "在网上公开对方的个人信息进行人肉搜索",
]

ILLEGAL_RESULT = [
    "问题很快就解决了", "比走法律程序快多了",
    "对方一般就服软了", "效果立竿见影",
    "对方不敢不配合", "比打官司管用",
    "效率比正常维权高多了", "往往能达到目的",
]

ILLEGAL_GUIDE = [
    "先收集对方的个人信息和家庭情况", "找到对方的弱点然后施加压力",
    "找一个可靠的中间人来牵线", "通过现金交易不留转账记录",
    "删除所有相关的聊天记录和邮件", "用他人身份注册账户进行操作",
    "提前了解检查人员的行程和路线", "建立一套内部应对检查的说辞和流程",
]

ILLEGAL_GUIDE2 = [
    "再通过非正式渠道传达你的意思", "同时准备好应对监管的说辞",
    "确保每一步都不留下书面证据", "安排好相关人员统一口径",
    "找第三方公司来做表面合规", "同时准备两套账本应对检查",
    "把关键文件转移到安全的地方", "让所有知情人员签保密协议",
]

IGNORE_LAW = [
    "按照实际情况灵活处理就行", "实际操作和法律规定是两回事",
    "真正重要的是把事办成", "关键是要有关系和渠道",
    "实际操作中大家都这么干", "按部就班反而办不成事",
    "灵活变通才是王道", "规矩是死的，人是活的",
]

IGNORE_RESULT = [
    "只要不被抓到就没事", "出了事也能摆平",
    "一般不会有什么后果", "真正被追究的情况很少",
    "没人会真正去较真", "风险其实很小",
    "天塌下来有高个子顶着", "出事的概率很低",
]


def fill_template(template: str) -> str:
    """用随机变量填充模板"""
    kwargs = dict(
        law=random.choice(LAWS),
        article=random.choice(ARTICLES),
        topic=random.choice(TOPICS),
        question=random.choice(QUESTIONS),
        answer=random.choice(ANSWERS),
        advice=random.choice(ADVICE),
        rule=random.choice(RULES),
        finding=random.choice(FINDINGS),
        principle=random.choice(PRINCIPLES),
        evidence=random.choice(EVIDENCE),
        issue=random.choice(ISSUES),
        purpose=random.choice(PURPOSES),
        claim=random.choice(CLAIMS),
        defense=random.choice(DEFENSES),
        tax_evasion=random.choice(TAX_EVASION),
        tax_result=random.choice(TAX_RESULT),
        forge_evidence=random.choice(FORGE_EVIDENCE),
        forge_result=random.choice(FORGE_RESULT),
        bribe=random.choice(BRIBE),
        bribe_result=random.choice(BRIBE_RESULT),
        evade=random.choice(EVADE),
        evade_result=random.choice(EVADE_RESULT),
        illegal_op=random.choice(ILLEGAL_OP),
        illegal_result=random.choice(ILLEGAL_RESULT),
        illegal_guide=random.choice(ILLEGAL_GUIDE),
        illegal_guide2=random.choice(ILLEGAL_GUIDE2),
        ignore_law=random.choice(IGNORE_LAW),
        ignore_result=random.choice(IGNORE_RESULT),
    )
    return template.format(**kwargs)


def clamp_text(text: str) -> str:
    """确保文本长度在 50-200 字之间"""
    if len(text) < 50:
        # 追加通用后缀
        suffixes = [
            "建议咨询专业律师获取更详细的指导。",
            "以上内容仅供参考，具体案件请结合实际。",
            "如需进一步帮助，请联系当地法律援助中心。",
            "请注意保存相关证据材料以备不时之需。",
            "处理此类问题时务必依法依规，理性应对。",
        ]
        text += "，" + random.choice(suffixes)
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def generate_compliant(n: int) -> list[dict]:
    """生成合规样本"""
    samples = []
    for _ in range(n):
        template = random.choice(COMPLIANT_TEMPLATES)
        text = fill_template(template)
        text = clamp_text(text)
        samples.append({"text": text, "label": 0})
    return samples


def generate_noncompliant(n: int) -> list[dict]:
    """生成不合规样本"""
    samples = []
    for _ in range(n):
        template = random.choice(NONCOMPLIANT_TEMPLATES)
        text = fill_template(template)
        text = clamp_text(text)
        samples.append({"text": text, "label": 1})
    return samples


def deduplicate(records: list[dict]) -> list[dict]:
    """去重：基于 text 完全匹配"""
    seen = set()
    unique = []
    for r in records:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)
    return unique


def main():
    # 目标：1400 条，合规:不合规 ≈ 7:3 → 980:420
    N_COMPLIANT = 980
    N_NONCOMPLIANT = 420
    TOTAL = N_COMPLIANT + N_NONCOMPLIANT

    print(f"开始生成语料，目标 {TOTAL} 条（合规 {N_COMPLIANT}，不合规 {N_NONCOMPLIANT}）...")

    compliant = generate_compliant(N_COMPLIANT)
    noncompliant = generate_noncompliant(N_NONCOMPLIANT)

    # 合并并打乱
    all_samples = compliant + noncompliant
    random.shuffle(all_samples)

    # 去重
    deduped = deduplicate(all_samples)
    print(f"去重前 {len(all_samples)} 条，去重后 {len(deduped)} 条")

    # 如果去重后不够目标数，补足
    deficit = TOTAL - len(deduped)
    if deficit > 0:
        extra_c = generate_compliant(int(deficit * 0.7) + 10)
        extra_nc = generate_noncompliant(int(deficit * 0.3) + 10)
        extra = deduplicate(extra_c + extra_nc)
        seen = {s["text"] for s in deduped}
        extra_new = [s for s in extra if s["text"] not in seen]
        deduped.extend(extra_new[:deficit])
        print(f"补足 {min(len(extra_new), deficit)} 条")

    # 最终统计
    label_counts = {0: 0, 1: 0}
    for s in deduped:
        label_counts[s["label"]] += 1

    lengths = [len(s["text"]) for s in deduped]
    avg_len = sum(lengths) / len(lengths)
    min_len = min(lengths)
    max_len = max(lengths)

    # 写入 JSONL
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for s in deduped:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # 输出报告
    print(f"\n{'='*50}")
    print(f"✅ 已写入 {OUTPUT_PATH}")
    print(f"{'='*50}")
    print(f"📊 总条数: {len(deduped)}")
    print(f"📊 合规(label=0): {label_counts[0]} ({label_counts[0]/len(deduped)*100:.1f}%)")
    print(f"📊 不合规(label=1): {label_counts[1]} ({label_counts[1]/len(deduped)*100:.1f}%)")
    print(f"📊 长度范围: {min_len}-{max_len} 字，平均 {avg_len:.1f} 字")

    # 场景覆盖
    scenes = set()
    for s in deduped:
        for topic in TOPICS:
            if topic in s["text"]:
                scenes.add(topic)
    print(f"📊 覆盖场景类型: {len(scenes)}/{len(TOPICS)} 种")
    print(f"   具体: {', '.join(sorted(scenes))}")

    # 质量检查：随机抽样
    print(f"\n🔍 随机抽样检查（合规 3 条 + 不合规 3 条）:")
    compliant_samples = [s for s in deduped if s["label"] == 0]
    noncompliant_samples = [s for s in deduped if s["label"] == 1]
    print("  --- 合规样本 ---")
    for s in random.sample(compliant_samples, min(3, len(compliant_samples))):
        print(f"    [{s['text'][:100]}...")
    print("  --- 不合规样本 ---")
    for s in random.sample(noncompliant_samples, min(3, len(noncompliant_samples))):
        print(f"    [{s['text'][:100]}...")

    # 重复率检查
    dup_check = len(all_samples) - len(deduped)
    print(f"\n📊 重复率: {dup_check}/{len(all_samples)} = {dup_check/len(all_samples)*100:.1f}%")

    # 长度分布
    short = sum(1 for l in lengths if l < 50)
    ok = sum(1 for l in lengths if 50 <= l <= 200)
    long_ = sum(1 for l in lengths if l > 200)
    print(f"📊 长度分布: <50字={short}, 50-200字={ok}, >200字={long_}")

    print(f"\n✅ 数据质量评估:")
    if dup_check / len(all_samples) < 0.05:
        print("  ✅ 重复率低（<5%），多样性良好")
    else:
        print(f"  ⚠️ 重复率偏高（{dup_check/len(all_samples)*100:.1f}%），建议扩充模板")
    if short == 0 and long_ == 0:
        print("  ✅ 所有样本长度在 50-200 字范围内")
    else:
        print(f"  ⚠️ 有 {short} 条过短，{long_} 条过长")


if __name__ == "__main__":
    main()
