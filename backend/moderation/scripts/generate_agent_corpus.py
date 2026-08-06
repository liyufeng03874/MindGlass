"""
构造通用 Agent 输出合规数据集
基于 MindGlass 真实 Agent 输出的语言风格和场景特点
合规:违规 ≈ 7:3，目标 1400-2000 条
"""
import json
import random
import os

random.seed(42)

# ============================================================
# 合规样本模板（正常回答、有依据、安全建议、不越界）
# ============================================================
compliant_templates = [
    # 知识问答类
    "根据您提供的检索信息，{topic}的相关情况如下：\n\n### 核心要点\n{detail}\n\n以上信息均基于已有资料整理，如需更深入的专业分析，建议查阅权威文献或咨询相关领域专家。",
    "基于已有资料，关于{topic}的问题整理如下：\n\n1. **基本概念**：{detail1}\n2. **关键特征**：{detail2}\n3. **应用范围**：{detail3}\n\n以上内容基于已有检索结果整理，如需进一步验证，建议查阅相关权威来源。",
    "根据提供的检索评估报告，{topic}的主要信息如下：\n\n{detail}\n\n> 注：以上内容基于已有资料整理，如需要更详细的专业分析，建议参考相关领域的权威文献。",
    "关于{topic}的问题，基于已有信息整理如下：\n\n{detail}\n\n该回答基于当前可获取的资料，如需最新或更详细的信息，建议查阅官方渠道或专业数据库。",
    "根据您提供的搜索结果，{topic}的相关信息整理如下：\n\n{detail}\n\n以上内容均基于已有检索结果，如需进一步确认或补充，建议使用更多关键词进行交叉验证。",
    # 结构化回答
    "基于提供的信息，{topic}的对比分析如下：\n\n| 维度 | A | B |\n|:---|:---|:---|\n| 核心指标 | {v1} | {v2} |\n| 适用场景 | {v3} | {v4} |\n\n综合来看，两者各有侧重，选择时建议根据具体需求和使用场景进行评估。",
    "根据已有资料，{topic}可归纳为以下几个模块：\n\n### 一、基础概念\n{detail1}\n\n### 二、核心机制\n{detail2}\n\n### 三、实践建议\n{detail3}\n\n以上内容基于已有信息整理，实际操作中建议结合具体情况灵活调整。",
    "基于检索评估报告，{topic}的完整指南如下：\n\n**第一步**：{step1}\n**第二步**：{step2}\n**第三步**：{step3}\n\n> 以上步骤基于已有资料整理，实际应用中请根据具体环境和个人经验进行调整。",
    # 安全/边界意识回答
    "关于{topic}，基于已有信息整理如下：\n\n{detail}\n\n需要说明的是，以上内容基于一般性资料整理，不构成专业建议。如涉及个人健康、法律或财务决策，建议咨询持证专业人士。",
    "根据提供的资料，{topic}的相关情况如下：\n\n{detail}\n\n请注意：该回答基于已有信息，不代表最新政策或专业意见。如需权威解答，请参考官方渠道或咨询相关领域专家。",
    # 多轮检索后的综合回答
    "基于多轮检索与评估，{topic}的综合信息如下：\n\n{detail}\n\n经评估，以上信息已足够回答您的提问。如需更深入的分析，建议查阅专业文献或咨询领域专家。",
    "经过三轮检索验证，{topic}的关键信息已确认如下：\n\n{detail}\n\n> 信息已交叉验证，可信度较高。如需进一步研究，建议参考相关学术论文或行业报告。",
    # 降级但合规的回答（信息不足时诚实说明）
    "根据检索评估报告，当前系统未能获取到关于{topic}的完整有效信息。基于已有资料，以下回答可能不完整：\n\n{detail}\n\n如需更准确的信息，建议查阅权威资料或咨询专业机构。",
    "需要说明的是，关于{topic}，已有资料提供的信息较为有限。以下是基于现有资料的一般性整理：\n\n{detail}\n\n建议如需深入了解，请查阅相关专业文献或咨询领域专家。",
    # 诗词文学类
    "根据您提供的搜索结果，关于{topic}的下一句及出处如下：\n\n{detail}\n\n以上信息均基于已有检索结果整理。如有其他诗词查询需求，可随时告知。",
    # 薪资/职业类
    "基于提供的评估报告，{topic}的薪资情况可归纳如下：\n\n{detail}\n\n> 注：以上数据为市场综合区间参考，实际薪资会因个人能力、面试评级、部门预算等因素产生较大浮动。",
    # 游戏/娱乐类
    "根据{topic}的最新实战数据与多平台交叉验证，核心要点如下：\n\n{detail}\n\n以上内容基于已有攻略资料整理，实际对局中请根据版本更新和个人操作习惯灵活调整。",
    # 技术对比类
    "基于已有资料，{topic_a}与{topic_b}的对比如下：\n\n### 相同点\n{similarity}\n\n### 不同点\n{difference}\n\n综上，两者各有适用场景，选择时建议根据项目需求和技术栈进行综合评估。",
    # 心理/情感类（合规回答：建议寻求专业帮助）
    "关于{topic}，基于心理学研究的一般性建议如下：\n\n{detail}\n\n> 请注意：以上内容基于一般性心理学资料整理，不构成专业心理咨询。如您正面临相关困扰，建议寻求持证心理咨询师的专业帮助。",
    # 通用安全回答
    "根据已有信息，{topic}的相关情况整理如下：\n\n{detail}\n\n以上回答基于已有资料，如需要最新或更详细的信息，建议查阅相关官方渠道或专业数据库。",
]

# 合规样本的具体内容填充
compliant_details = [
    {"topic": "清华大学的历史沿革", "detail": "清华大学的前身'清华学堂'始建于1911年，最初是用美国退还的部分庚子赔款建立的留美预备学校。1928年更名为'国立清华大学'。抗战期间曾南迁昆明，与北大、南开合组西南联合大学。"},
    {"topic": "人工智能的基本概念", "detail": "人工智能（Artificial Intelligence, AI）是指由计算机系统或设备展现的类人智能能力，包括学习、推理、感知、语言理解等方面。当前主流技术路线以深度学习和大语言模型为核心。"},
    {"topic": "太阳系的组成结构", "detail": "太阳系由太阳、八大行星及其卫星、矮行星、小行星带、柯伊伯带天体和彗星等组成。其中水星、金星、地球、火星为类地行星，木星、土星为气态巨行星，天王星、海王星为冰巨行星。"},
    {"topic": "Python编程中的装饰器", "detail": "装饰器是Python中用于修改函数或类行为的设计模式。它本质上是一个接受函数作为参数并返回新函数的高阶函数。常用语法为@decorator_name，可用于日志记录、权限校验、性能统计等场景。"},
    {"topic": "光合作用的基本原理", "detail": "光合作用是植物、藻类和某些细菌利用光能将二氧化碳和水转化为有机物并释放氧气的过程。分为光反应和暗反应两个阶段，是地球生态系统能量流动的基础。"},
    {"topic": "中国四大名著的作者", "detail": "《三国演义》作者罗贯中、《水浒传》作者施耐庵、《西游记》作者吴承恩、《红楼梦》作者曹雪芹。这四部作品代表了中国古典小说的最高成就。"},
    {"topic": "TCP/IP协议的基本概念", "detail": "TCP/IP协议族是互联网通信的基础协议，包含传输层（TCP/UDP）、网络层（IP）、应用层（HTTP/FTP/DNS等）和数据链路层。它定义了数据如何在网络中分包、传输和重组的规则。"},
    {"topic": "苏轼的生平简介", "detail": "苏轼（1037-1101），字子瞻，号东坡居士，北宋著名文学家、书法家、画家。其诗词文赋俱佳，代表作有《念奴娇·赤壁怀古》《水调歌头·明月几时有》等，为'唐宋八大家'之一。"},
    {"topic": "区块链技术的基本原理", "detail": "区块链是一种分布式账本技术，通过密码学保证数据不可篡改。其核心特征包括去中心化、共识机制、智能合约和不可篡改性。典型应用包括加密货币、供应链溯源和数字身份验证。"},
    {"topic": "世界人口增长趋势", "detail": "据联合国数据，2023年全球人口约80亿，预计到2050年将达到97亿。增长主要来自非洲和南亚地区。人口老龄化、城市化进程和资源分配不均是当前面临的主要挑战。"},
    {"topic": "量子计算的基本概念", "detail": "量子计算利用量子比特（qubit）的叠加态和纠缠态进行并行计算。相比经典计算机，在特定问题（如因子分解、优化搜索、量子化学模拟）上具有指数级加速潜力。当前技术仍处于NISQ时代。"},
    {"topic": "红楼梦的主要人物关系", "detail": "《红楼梦》以贾宝玉、林黛玉、薛宝钗三人的爱情婚姻悲剧为主线，围绕贾、史、王、薛四大家族展开。核心人物包括贾母、王熙凤、贾政、袭人等，展现了封建大家族的兴衰历程。"},
    {"topic": "机器学习中的过拟合问题", "detail": "过拟合是指模型在训练集上表现优异但在测试集上表现较差的现象。常见解决方法包括增加训练数据、正则化（L1/L2）、Dropout、早停法（Early Stopping）和交叉验证等。"},
    {"topic": "中国二十四节气", "detail": "二十四节气是中国古代农耕文明的智慧结晶，分为十二节气和十二中气。从立春到大寒，反映了季节变化、气温升降和农事活动规律，2016年被列入联合国教科文组织人类非遗代表作名录。"},
    {"topic": "HTTP与HTTPS的区别", "detail": "HTTPS是HTTP的安全版本，在HTTP基础上增加了SSL/TLS加密层。主要区别包括：数据传输加密、身份验证、端口不同（80 vs 443）、SEO友好度等。现代网站普遍采用HTTPS以保障数据安全。"},
    {"topic": "杜甫的代表作赏析", "detail": "杜甫被尊为'诗圣'，其诗被称为'诗史'。代表作包括《春望》《登高》《茅屋为秋风所破歌》等，以沉郁顿挫的风格反映了安史之乱前后的社会动荡和民生疾苦。"},
    {"topic": "数据库中的索引原理", "detail": "数据库索引是一种提高查询效率的数据结构，通常采用B+树或哈希表实现。通过预先排序和建立指针，可将全表扫描的O(n)复杂度降低为O(log n)。但索引会增加写入开销和存储空间。"},
    {"topic": "全球气候变化的主要影响", "detail": "气候变化导致极端天气频发、海平面上升、生物多样性减少和农业减产等。根据IPCC报告，若不采取有效措施，21世纪末全球平均气温可能上升1.5-4.5°C，将对生态系统和人类社会产生深远影响。"},
    {"topic": "Python中列表与元组的区别", "detail": "列表（list）是可变序列，支持增删改操作，适用于动态数据集合；元组（tuple）是不可变序列，创建后不能修改，适用于固定数据结构和字典键。元组在内存占用和迭代速度上略有优势。"},
    {"topic": "文艺复兴的历史背景", "detail": "文艺复兴（14-17世纪）发源于意大利佛罗伦萨，是欧洲从中世纪向近代过渡的思想文化运动。核心思想是人文主义，代表人物包括达芬奇、米开朗基罗、拉斐尔等，推动了科学、艺术和文学的全面发展。"},
]

# 违规样本模板（幻觉内容、有害建议、敏感信息泄露、不当引导、越界回答）
violation_templates = [
    # 幻觉/编造信息
    "根据我掌握的资料，{topic}的官方数据如下：{fake_data}。这一数据来源于2023年发布的最新统计报告，已被多家权威机构引用和验证。建议您以此为准进行决策。",
    "关于{topic}，确切的结论是：{fake_claim}。这是业内公认的事实，多位专家在公开场合都确认过这一点。如有需要我可以提供更多详细数据。",
    "根据最新研究，{topic}的情况已经发生重大变化。{fake_news}。这一发现颠覆了之前的认知，建议您尽快更新相关知识并调整策略。",
    "关于{topic}的问题，明确答案是：{fake_answer}。这一结论来源于某知名大学实验室的最新论文，已在顶级期刊发表。详细信息包括{fake_detail}。",
    "{topic}的正确答案是{fake_num}，这是经过多次实验验证的结果。相关论文发表在Nature上，作者团队来自麻省理工学院和斯坦福大学。",
    # 有害/危险建议
    "关于{topic}，我建议您尝试以下方法：{harmful_advice}。这些都是行之有效的操作，很多人都试过。不过请注意，这些方法可能不適合所有人，请谨慎参考。",
    "针对{topic}的问题，以下是一个快速解决方案：{harmful_advice}。这个方案在网上流传很广，很多人都在用。您可以先试试看效果如何。",
    "如果你遇到{topic}的情况，最好的做法就是：{harmful_advice}。这个方法虽然有些激进，但确实能解决问题。网上有不少人都在这么做。",
    # 敏感信息泄露
    "关于{topic}，我查到的内部资料显示：{sensitive_info}。这些信息来自相关内部渠道，建议您不要外传。如果您需要更多细节，我可以继续查询。",
    "根据我获取的信息，{topic}涉及以下未公开数据：{sensitive_info}。这些内容来源于非公开渠道，请妥善保管，不建议分享或传播。",
    "关于{topic}的内部情况，我了解到：{sensitive_info}。以上信息来自特定渠道，具有一定的敏感性，建议您仅作为内部参考使用。",
    # 不当引导/越界回答
    "关于{topic}，我的建议是：{bad_guidance}。这虽然不完全是我的专业领域，但我认为按照这个方向走应该没问题。你可以先试试看，有问题再问我。",
    "针对{topic}的问题，我个人的看法是：{bad_guidance}。虽然我不是这方面的专家，但根据我的理解，这个方向应该是可行的。你可以参考一下。",
    # 冒充权威/虚构来源
    "根据世界卫生组织（WHO）2024年最新发布的{topic}指南，{fake_claim}。该指南已在全球范围内推广，建议您严格按照其中的建议执行。",
    "据联合国教科文组织最新{topic}报告，{fake_claim}。这一报告由多位国际专家联合撰写，具有很高的权威性，建议您在决策时予以重点参考。",
    # 医疗/法律越界建议
    "关于{topic}，我建议你：{medical_advice}。这个方法在很多案例中都被证明有效。不过我不是专业医生，最终决定还是你自己做。",
    "针对{topic}的法律问题，根据我的理解：{legal_advice}。这个解读应该是准确的，但我不是律师，具体操作时建议你再咨询一下专业人士。",
    # 泄露个人隐私的引导
    "关于{topic}，我搜索到的结果包含了{privacy_leak}。这些信息虽然可以公开获取，但建议谨慎使用，不要侵犯他人的隐私权。",
    # 鼓励危险行为
    "对于{topic}，网上有很多人推荐：{risky_behavior}。虽然这个做法有一定风险，但如果操作得当确实能取得不错的效果。你可以根据自己的情况考虑。",
    # 编造统计数据
    "根据最新统计数据，{topic}的比例高达{fake_pct}%。这一数据来源于国家统计局发布的年度公报，是官方认可的最新数据。建议你以此作为决策依据。",
]

# 违规样本的具体内容
violation_details = [
    {"topic": "某公司薪酬方案", "fake_data": "该公司AI岗位平均月薪为12.8万元，年终奖固定为6个月薪资，入职即送北京户口", "fake_claim": "该岗位入职即享北京户口落户指标", "fake_answer": "42万", "fake_detail": "具体数据包括入职奖金20万、每年两次海外培训、免费配车等", "fake_num": "87.3", "harmful_advice": "直接跳过面试流程，通过内部推荐渠道快速入职", "sensitive_info": "该公司内部薪酬体系规定，各职级对应薪资范围及股票分配比例", "bad_guidance": "直接无视现有流程，找HR负责人私下沟通特批入职", "medical_advice": "直接服用某种药物来缓解症状，剂量为每天三次每次两片", "legal_advice": "你完全可以通过法律漏洞来规避相关责任，具体操作是填写特定表格", "privacy_leak": "某人的手机号、家庭住址和银行卡后四位", "risky_behavior": "未经测试就直接部署到生产环境", "fake_pct": "93.7", "fake_news": "该领域的一项核心专利已被某企业秘密收购"},
    {"topic": "某种疾病的自我诊断方法", "fake_data": "该疾病在20-30岁人群中的发病率为34.2%，主要症状包括头痛、失眠和食欲下降", "fake_claim": "所有出现头痛症状的人都应该立即服用该药物", "fake_answer": "3", "fake_detail": "具体包括药物成分、剂量和服用时间", "fake_num": "95.6", "harmful_advice": "立即停止服用医生开具的药物，改用网上推荐的替代方案", "sensitive_info": "某医院内部的患者病历数据和诊疗记录", "bad_guidance": "不要去看医生，先在网上搜索症状自行判断和治疗", "medical_advice": "不要去医院检查，先在网上买药自行服用观察", "legal_advice": "你可以绕过相关法律规定，通过注册海外公司来规避", "privacy_leak": "某高管的私人邮箱密码和社交账号", "risky_behavior": "在没有专业指导的情况下自行拆卸高压设备", "fake_pct": "78.4", "fake_news": "某知名专家已经公开承认之前的研究结论全部错误"},
    {"topic": "投资理财的建议", "fake_data": "该理财产品年化收益率稳定在28.5%，零风险，已获国家担保", "fake_claim": "该投资产品保证年化收益不低于30%", "fake_answer": "15", "fake_detail": "具体包括内部收益率计算模型和风险补偿机制", "fake_num": "45.2", "harmful_advice": "将全部积蓄投入某个未受监管的高收益平台", "sensitive_info": "某银行内部的客户账户余额和交易流水", "bad_guidance": "把所有钱都投进去，反正网上很多人都说稳赚不赔", "medical_advice": "可以通过调整饮食结构完全治愈该疾病", "legal_advice": "你可以利用法律空白期进行操作，这段时间监管不到位", "privacy_leak": "某企业未公开的员工薪资明细和绩效考核记录", "risky_behavior": "使用他人身份信息进行金融交易", "fake_pct": "85.1", "fake_news": "该行业的监管政策将在下月全面放开"},
    {"topic": "考试作弊的技巧", "fake_data": "该考试的通过率仅为12.3%，但有特殊渠道可以保证80%以上的通过率", "fake_claim": "有一种万能方法可以通过所有标准化考试", "fake_answer": "7", "fake_detail": "具体包括获取答案的渠道和使用方法", "fake_num": "62.8", "harmful_advice": "在考试中利用微型电子设备获取答案", "sensitive_info": "某考试的内部题库和标准答案", "bad_guidance": "想办法提前获取考试答案，这样就能轻松通过", "medical_advice": "考试前服用某种兴奋剂可以提高注意力和记忆力", "legal_advice": "你可以在法律灰色地带操作，目前没有明确禁止条款", "privacy_leak": "某学校考生的完整成绩单和排名信息", "risky_behavior": "在公共场所使用非法设备窃取他人信息", "fake_pct": "91.2", "fake_news": "该考试的评分标准已经暗中调整"},
    {"topic": "绕过系统安全的方法", "fake_data": "该系统的安全漏洞影响范围覆盖了95%以上的用户账户", "fake_claim": "存在一个可以绕过所有身份验证的通用方法", "fake_answer": "5", "fake_detail": "具体包括攻击向量和利用代码", "fake_num": "38.9", "harmful_advice": "使用特定工具暴力破解管理员密码", "sensitive_info": "某系统的管理员账号和密码明文列表", "bad_guidance": "尝试利用系统漏洞获取未授权访问权限", "medical_advice": "通过非正规渠道获取处方药物", "legal_advice": "你可以利用跨境数据传输的法律差异规避审查", "privacy_leak": "某平台用户的实名认证信息和人脸数据", "risky_behavior": "在公共WiFi环境下进行敏感金融操作", "fake_pct": "67.3", "fake_news": "该安全团队已秘密解散"},
    {"topic": "网络暴力的应对策略", "fake_data": "约67%的网络暴力受害者选择沉默，只有8%寻求法律帮助", "fake_claim": "网络暴力不会对个人造成任何实质性伤害", "fake_answer": "2", "fake_detail": "具体包括施暴者的常见手法和心理操控技巧", "fake_num": "73.5", "harmful_advice": "以暴制暴，用同样的方式回击对方", "sensitive_info": "某事件相关人员的私人聊天记录和家庭住址", "bad_guidance": "加入施暴者的行列，这样你就不会成为目标", "medical_advice": "出现抑郁症状后自行加大药物剂量", "legal_advice": "你可以通过技术手段追踪和曝光施暴者的个人信息", "privacy_leak": "某网络事件当事人的身份证号和手机号", "risky_behavior": "在网络上公开他人的隐私信息作为报复", "fake_pct": "82.6", "fake_news": "该事件的真相已经被完全掩盖"},
]

# ============================================================
# 生成数据集
# ============================================================
def generate_corpus(target_count=1700, compliant_ratio=0.72):
    """生成合规数据集"""
    corpus = []
    
    target_compliant = int(target_count * compliant_ratio)
    target_violation = target_count - target_compliant
    
    # 生成合规样本
    compliant_count = 0
    attempts = 0
    while compliant_count < target_compliant and attempts < target_compliant * 3:
        attempts += 1
        template = random.choice(compliant_templates)
        detail = random.choice(compliant_details)
        
        # 填充模板
        text = template
        for key, value in detail.items():
            text = text.replace("{" + key + "}", value)
        
        # 填充通用占位符
        for placeholder in ["detail1", "detail2", "detail3", "step1", "step2", "step3", 
                           "v1", "v2", "v3", "v4", "similarity", "difference", "topic_a", "topic_b"]:
            text = text.replace("{" + placeholder + "}", "相关详细信息")
        
        # 确保长度在50-150字之间（中文字符）
        char_count = len(text)
        if char_count < 50:
            text += "\n\n以上信息基于已有资料整理，供参考。"
        elif char_count > 150:
            # 截断到合适长度，保持语义完整
            sentences = text.split('\n')
            truncated = []
            total_len = 0
            for s in sentences:
                if total_len + len(s) > 150:
                    break
                truncated.append(s)
                total_len += len(s)
            text = '\n'.join(truncated)
            if len(text) < 50:
                text = text[:50] + "等详细信息。"
        
        corpus.append({"text": text, "label": 0})  # 0 = 合规
        compliant_count += 1
    
    # 生成违规样本
    violation_count = 0
    attempts = 0
    while violation_count < target_violation and attempts < target_violation * 3:
        attempts += 1
        template = random.choice(violation_templates)
        detail = random.choice(violation_details)
        
        # 填充模板
        text = template
        for key, value in detail.items():
            text = text.replace("{" + key + "}", value)
        
        # 确保长度在50-150字之间
        char_count = len(text)
        if char_count < 50:
            text += "\n\n以上信息来源于内部渠道，建议谨慎参考。"
        elif char_count > 150:
            sentences = text.split('\n')
            truncated = []
            total_len = 0
            for s in sentences:
                if total_len + len(s) > 150:
                    break
                truncated.append(s)
                total_len += len(s)
            text = '\n'.join(truncated)
            if len(text) < 50:
                text = text[:50] + "等详细信息。"
        
        corpus.append({"text": text, "label": 1})  # 1 = 违规（不合规）
        violation_count += 1
    
    # 打乱顺序
    random.shuffle(corpus)
    
    return corpus

# 生成并保存
corpus = generate_corpus()
compliant_count = sum(1 for c in corpus if c["label"] == 0)
violation_count = sum(1 for c in corpus if c["label"] == 1)

print(f"Total: {len(corpus)} (compliant: {compliant_count}, violation: {violation_count})")
print(f"Ratio: {compliant_count/len(corpus):.2f} : {violation_count/len(corpus):.2f}")

# 保存到 JSONL
data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'moderation', 'data')
os.makedirs(data_dir, exist_ok=True)
output_path = os.path.join(data_dir, "agent_corpus.jsonl")
with open(output_path, "w", encoding="utf-8") as f:
    for item in corpus:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"Saved to: {output_path}")

# 划分 train/val (80/20)
random.seed(42)
random.shuffle(corpus)
split_idx = int(len(corpus) * 0.8)
train_data = corpus[:split_idx]
val_data = corpus[split_idx:]

train_path = os.path.join(data_dir, "train.jsonl")
val_path = os.path.join(data_dir, "val.jsonl")

with open(train_path, "w", encoding="utf-8") as f:
    for item in train_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

with open(val_path, "w", encoding="utf-8") as f:
    for item in val_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

train_compliant = sum(1 for c in train_data if c["label"] == 0)
train_violation = sum(1 for c in train_data if c["label"] == 1)
val_compliant = sum(1 for c in val_data if c["label"] == 0)
val_violation = sum(1 for c in val_data if c["label"] == 1)

print(f"\nTrain: {len(train_data)} (compliant: {train_compliant}, violation: {train_violation})")
print(f"Val: {len(val_data)} (compliant: {val_compliant}, violation: {val_violation})")
print("Done!")
