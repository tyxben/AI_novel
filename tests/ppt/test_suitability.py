"""文档适配性预检测试"""

from src.ppt.document_analyzer import SuitabilityResult, check_ppt_suitability


class TestSuitabilityBasic:
    """基础适配性检查。"""

    def test_empty_text(self):
        r = check_ppt_suitability("")
        assert not r.suitable
        assert r.score == 0

    def test_whitespace_only(self):
        r = check_ppt_suitability("   \n\n  ")
        assert not r.suitable

    def test_too_short(self):
        r = check_ppt_suitability("这是一段很短的文字")
        assert not r.suitable
        assert "太短" in r.message

    def test_normal_prose(self):
        """正常的文章内容应该适合。"""
        text = (
            "人工智能（AI）正在深刻改变我们的生活方式和工作模式。"
            "从智能语音助手到自动驾驶汽车，从医疗诊断到金融分析，"
            "AI 的应用场景不断拓展。根据最新研究报告，2024年全球"
            "AI市场规模预计将达到5000亿美元，较去年增长30%。"
            "这一增长主要得益于大语言模型的突破性进展，以及"
            "企业对AI技术的大规模采用。\n\n"
            "在教育领域，AI辅助教学系统已在全球超过100个国家部署。"
            "这些系统能够根据学生的学习进度和特点，自动调整教学内容"
            "和难度，实现真正的个性化学习。研究表明，使用AI辅助教学"
            "的学生，平均成绩提升了15%，学习效率提高了25%。\n\n"
            "然而，AI的快速发展也带来了新的挑战。数据隐私、算法偏见"
            "和就业冲击等问题需要我们认真面对。行业专家建议，应该建立"
            "完善的AI治理框架，在推动技术创新的同时，确保AI的安全"
            "和负责任使用。"
        )
        r = check_ppt_suitability(text)
        assert r.suitable
        assert r.score >= 60


class TestCodeHeavy:
    """代码占比过高的文档。"""

    def test_mostly_code(self):
        """超过60%是代码的文档不适合。"""
        text = (
            "# 安装指南\n\n"
            "```bash\n"
            "pip install tensorflow\n"
            "pip install numpy\n"
            "pip install pandas\n"
            "pip install scikit-learn\n"
            "pip install matplotlib\n"
            "```\n\n"
            "```python\n"
            "import tensorflow as tf\n"
            "import numpy as np\n"
            "model = tf.keras.Sequential([\n"
            "    tf.keras.layers.Dense(128, activation='relu'),\n"
            "    tf.keras.layers.Dense(64, activation='relu'),\n"
            "    tf.keras.layers.Dense(10, activation='softmax'),\n"
            "])\n"
            "model.compile(optimizer='adam', loss='categorical_crossentropy')\n"
            "model.fit(x_train, y_train, epochs=10)\n"
            "```\n\n"
            "```python\n"
            "results = model.evaluate(x_test, y_test)\n"
            "print(f'Accuracy: {results[1]:.2f}')\n"
            "predictions = model.predict(x_new)\n"
            "```\n"
        )
        r = check_ppt_suitability(text)
        assert not r.suitable
        assert any("代码" in reason for reason in r.reasons)

    def test_moderate_code_with_prose(self):
        """适量代码 + 充足文字说明应该可以。"""
        text = (
            "# TensorFlow 深度学习入门\n\n"
            "深度学习是机器学习的一个重要分支，它通过模拟人脑神经网络"
            "的结构来处理复杂的数据。TensorFlow 是 Google 开发的"
            "开源深度学习框架，广泛应用于图像识别、自然语言处理等领域。\n\n"
            "## 核心概念\n\n"
            "张量（Tensor）是 TensorFlow 中的基本数据单位，可以理解为"
            "多维数组。计算图（Graph）定义了运算的流程和依赖关系。\n\n"
            "## 简单示例\n\n"
            "```python\n"
            "import tensorflow as tf\n"
            "model = tf.keras.Sequential([...])\n"
            "```\n\n"
            "通过以上代码，我们可以快速搭建一个神经网络模型。"
            "TensorFlow 的高层API（Keras）大大简化了模型的定义过程。\n\n"
            "## 应用场景\n\n"
            "目前 TensorFlow 已被广泛应用于以下领域：\n"
            "- 图像分类和目标检测\n"
            "- 自然语言理解和生成\n"
            "- 推荐系统和搜索排序\n"
            "- 医疗影像分析\n"
        )
        r = check_ppt_suitability(text)
        assert r.suitable


class TestApiDocs:
    """API文档/命令行文档。"""

    def test_curl_heavy(self):
        """大量 curl 命令的 API 文档不适合。"""
        text = (
            "# API Reference\n\n"
            "## Send Message\n\n"
            "```bash\n"
            "curl -X POST http://localhost:3000/api/message \\\n"
            "  -H 'Authorization: Bearer YOUR_API_KEY' \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\"to\": \"agent_id\", \"content\": \"hello\"}'\n"
            "```\n\n"
            "## Get Messages\n\n"
            "```bash\n"
            "curl http://localhost:3000/api/messages \\\n"
            "  -H 'Authorization: Bearer YOUR_API_KEY'\n"
            "```\n\n"
            "## Heartbeat\n\n"
            "```bash\n"
            "curl -X POST http://localhost:3000/api/heartbeat \\\n"
            "  -H 'Authorization: Bearer YOUR_API_KEY'\n"
            "```\n\n"
            "## Register Webhook\n\n"
            "```bash\n"
            "curl -X POST http://localhost:3000/api/webhooks \\\n"
            "  -H 'Authorization: Bearer YOUR_API_KEY' \\\n"
            "  -d '{\"event\": \"message_received\", \"url\": \"https://your-agent.com/webhook\"}'\n"
            "```\n"
        )
        r = check_ppt_suitability(text)
        assert not r.suitable

    def test_real_world_md_file(self):
        """测试用户提到的实际文件类型：改进方案文档。"""
        # 模拟那种 API 改进方案文档
        text = (
            "# Skill.md 改进方案\n\n"
            "## 核心改动\n\n"
            "```markdown\n"
            "### Agent Messaging (Chat)\n\n"
            "**How it works:**\n"
            "1. Send: `POST /api/message`\n"
            "2. Check: `POST /api/heartbeat`\n"
            "3. Read: `GET /api/messages`\n"
            "```\n\n"
            "```bash\n"
            "curl -X POST http://localhost:3000/api/webhooks \\\n"
            "  -H 'Authorization: Bearer YOUR_API_KEY' \\\n"
            "  -d '{\"event\": \"message_received\"}'\n"
            "```\n\n"
            "```python\n"
            "import time, requests\n"
            "while True:\n"
            "    hb = requests.post('http://localhost:3000/api/heartbeat').json()\n"
            "    if hb.get('unread_count', 0) > 0:\n"
            "        inbox = requests.get('http://localhost:3000/api/messages').json()\n"
            "    time.sleep(20)\n"
            "```\n\n"
            "### 总结\n\n"
            "- ✅ 增加警告框\n"
            "- ✅ 提供轮询伪代码\n"
            "- ❌ 不增加新端点\n"
            "- ❌ 不改动现有 API\n"
        )
        r = check_ppt_suitability(text)
        assert not r.suitable


class TestEdgeCases:
    """边界情况。"""

    def test_short_but_substantial(self):
        """较短但有实质内容，适合生成。"""
        text = (
            "2024年第一季度业绩报告\n\n"
            "本季度营收达到5.2亿元，同比增长35%。净利润1.8亿元，"
            "利润率保持在34.6%。新增客户1200家，客户续费率95%。"
            "研发投入占比18%，推出了3款新产品。\n\n"
            "市场拓展方面，我们成功进入东南亚三个新市场，"
            "建立了本地化运营团队。产品质量持续提升，"
            "客户满意度达到92分，创历史新高。\n\n"
            "下一季度重点：加大研发投入，推进海外市场扩张，"
            "优化供应链管理，降低运营成本。预计下季度营收"
            "将突破6亿元大关。"
        )
        r = check_ppt_suitability(text)
        assert r.suitable
        assert r.score >= 60

    def test_checklist_heavy(self):
        """纯清单列表文档。"""
        text = "\n".join(
            [f"- 待办事项 {i}: 完成模块{i}的开发和测试工作" for i in range(30)]
        )
        r = check_ppt_suitability(text)
        # 纯清单，score 降低
        assert r.score < 90

    def test_score_range(self):
        """score 始终在 0-100 之间。"""
        # 极端差的内容
        r1 = check_ppt_suitability("x" * 100)
        assert 0 <= r1.score <= 100

        # 极端好的内容
        good_text = "这是一份关于人工智能发展趋势的详细分析报告。" * 50
        r2 = check_ppt_suitability(good_text)
        assert 0 <= r2.score <= 100


class TestSuitabilityResult:
    """SuitabilityResult 模型。"""

    def test_suitable_empty_message(self):
        r = SuitabilityResult(True, 80, [])
        assert r.message == ""

    def test_unsuitable_has_message(self):
        r = SuitabilityResult(False, 20, ["代码太多", "文字太少"])
        assert "代码太多" in r.message
        assert "文字太少" in r.message
        assert "不太适合" in r.message
