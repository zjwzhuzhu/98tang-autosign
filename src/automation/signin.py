"""
签到核心模块

提供网站登录和签到的核心功能
"""

import os
import re
import logging
from typing import Optional, Dict, Any

from ..browser.helpers import BrowserHelper
from ..browser.element_finder import ElementFinder
from ..utils.timing import TimingManager


class SignInManager:
    """签到管理器"""

    def __init__(
        self, driver, config: Dict[str, Any], logger: Optional[logging.Logger] = None
    ):
        """
        初始化签到管理器

        Args:
            driver: WebDriver实例
            config: 配置字典
            logger: 日志器
        """
        self.driver = driver
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.element_finder = ElementFinder(driver, logger)

        # 网站配置
        self.base_url = config.get("base_url", "https://www.sehuatang.org")
        self.home_url = self.base_url
        self.sign_url = f"{self.base_url}/plugin.php?id=dsu_paulsign:sign"

        # 认证配置
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.enable_security_question = config.get("enable_security_question", False)
        self.security_answer = config.get("security_answer", "")
        self.security_question = config.get("security_question", "")

        # 签到点击尝试次数（防止按钮点击方式无限重试）
        self._signin_click_attempts = 0

    def handle_age_verification(self) -> bool:
        """
        处理年龄验证

        Returns:
            是否处理成功
        """
        try:
            self.logger.debug("开始检查年龄验证页面")

            age_selectors = [
                "a[href*='agecheck']",
                "//a[contains(text(), '满18岁')]",
                "//a[contains(text(), '请点此进入')]",
            ]

            age_link = self.element_finder.find_by_selectors(age_selectors, timeout=3)
            if age_link:
                self.logger.info("检测到年龄验证页面，正在处理")
                link_text = age_link.text
                link_href = age_link.get_attribute("href")
                self.logger.debug(
                    f"找到年龄验证链接 - 文本: '{link_text}', href: '{link_href}'"
                )

                BrowserHelper.safe_click(self.driver, age_link, self.logger)
                TimingManager.smart_page_wait(
                    self.driver, ["#main", ".wp", "body"], self.logger
                )

                self.logger.info("年龄验证处理完成")
                return True

            self.logger.debug("未检测到年龄验证页面，无需处理")
            return True  # 无需验证

        except Exception as e:
            self.logger.warning(f"年龄验证处理失败: {e}")
            return True  # 继续执行

    def check_login_status(self) -> bool:
        """
        检查登录状态

        Returns:
            是否已登录
        """
        try:
            self.logger.debug("开始检查登录状态")

            # 首先检查是否有登录错误消息
            error_message = self.check_login_error_message()
            if error_message:
                self.logger.error(f"登录失败，错误信息: {error_message}")
                return False

            username_selectors = [
                f"//strong[contains(text(), '{self.username}')]",
                f"//a[contains(text(), '{self.username}')]",
                ".vwmy strong",
                "//div[@class='vwmy']//strong",
            ]

            username_element = self.element_finder.find_by_selectors(
                username_selectors, timeout=3
            )

            if username_element:
                element_text = username_element.text
                self.logger.debug(f"找到用户名元素，文本内容: '{element_text}'")
                if self.username in element_text:
                    self.logger.debug("用户名匹配成功，已登录")
                    return True
                else:
                    self.logger.debug(
                        f"用户名不匹配，期望: '{self.username}', 实际: '{element_text}'"
                    )

            # 检查其他登录指示器
            login_indicators = [
                "//a[contains(@href, 'logging.php?action=logout')]",
                "//a[contains(text(), '退出')]",
                ".vwmy",
            ]

            indicator = self.element_finder.find_by_selectors(
                login_indicators, timeout=3
            )

            if indicator:
                self.logger.debug("找到登录指示器")
                return True

            self.logger.debug("未找到任何登录指示器")
            return False

        except Exception as e:
            self.logger.warning(f"检查登录状态失败: {e}")
            return False

    def check_login_error_message(self) -> Optional[str]:
        """
        检查登录错误消息

        Returns:
            错误消息文本，如果没有错误则返回None
        """
        try:
            # 检查页面源代码中的JavaScript错误处理
            page_source = self.driver.page_source

            # 检查密码错误次数过多的提示
            if "密码错误次数过多" in page_source:
                import re

                # 提取具体的错误消息
                error_pattern = r"errorhandle_login\('([^']+)'"
                match = re.search(error_pattern, page_source)
                if match:
                    error_msg = match.group(1)
                    self.logger.warning(f"检测到账号锁定: {error_msg}")
                    return error_msg
                return "密码错误次数过多，账号已被临时锁定"

            # 检查其他常见的登录错误消息
            error_indicators = [
                "用户名或密码错误",
                "账号已被禁用",
                "验证码错误",
                "安全提问答案错误",
                "登录失败",
                "请重新登录",
            ]

            for error_text in error_indicators:
                if error_text in page_source:
                    return error_text

            # 检查弹窗中的错误消息
            error_selectors = [
                "#ntcwin .pc_inner i",  # 错误弹窗
                "#returnmessage_Luu4S",  # 登录返回消息
                ".alert_error",  # 错误提示
                ".error",  # 通用错误
            ]

            for selector in error_selectors:
                try:
                    error_element = self.element_finder.find_by_selectors(
                        [selector], timeout=1
                    )
                    if error_element and error_element.text.strip():
                        error_text = error_element.text.strip()
                        if any(
                            keyword in error_text
                            for keyword in ["错误", "失败", "禁用"]
                        ):
                            return error_text
                except:
                    continue

            return None

        except Exception as e:
            self.logger.debug(f"检查登录错误消息时出错: {e}")
            return None

    def fill_login_form(self) -> bool:
        """
        填写登录表单

        Returns:
            是否填写成功
        """
        try:
            self.logger.debug("开始填写登录表单")

            # 用户名输入框
            username_selectors = [
                "#fwin_login input[name='username']",
                "#username",
                "input[name='username']",
            ]

            username_input = self.element_finder.find_by_selectors(username_selectors)
            if not username_input:
                self.logger.error("未找到用户名输入框")
                return False

            self.logger.debug("找到用户名输入框，开始填写")
            username_input.clear()
            username_input.send_keys(self.username)
            self.logger.debug(
                f"用户名已填写: {self.username[:2]}{'*' * (len(self.username) - 2) if len(self.username) > 2 else '***'}"
            )

            # 密码输入框
            password_selectors = [
                "#fwin_login input[name='password']",
                "#password",
                "input[name='password']",
            ]

            password_input = self.element_finder.find_by_selectors(password_selectors)
            if not password_input:
                self.logger.error("未找到密码输入框")
                return False

            self.logger.debug("找到密码输入框，开始填写")
            password_input.clear()
            password_input.send_keys(self.password)
            self.logger.debug("密码已填写（已掩码）")

            TimingManager.smart_wait(TimingManager.NAVIGATION_DELAY, 1.0, self.logger)
            self.logger.debug("登录表单填写完成")
            return True

        except Exception as e:
            self.logger.error(f"填写登录表单失败: {e}")
            return False

    def handle_security_question(self) -> bool:
        """
        处理安全提问

        Returns:
            是否处理成功
        """
        if not self.enable_security_question:
            return True

        try:
            question_select = self.element_finder.find_by_selectors(
                ["select[name='questionid']", "#questionid"]
            )

            if not question_select:
                return True  # 无安全提问

            self.logger.info("处理安全提问")

            # 选择安全问题
            from selenium.webdriver.common.by import By

            options = question_select.find_elements(By.TAG_NAME, "option")
            for option in options:
                if self.security_question in option.text:
                    option.click()
                    break

            # 填写答案
            answer_input = self.element_finder.find_by_selectors(
                ["input[name='answer']", "#answer"]
            )

            if answer_input:
                answer_input.clear()
                answer_input.send_keys(self.security_answer)
                self.logger.debug("安全提问答案已填写（已掩码）")
                return True

            return False

        except Exception as e:
            self.logger.error(f"处理安全提问失败: {e}")
            return False

    def login(self) -> bool:
        """
        登录网站

        Returns:
            是否登录成功
        """
        try:
            self.logger.info("开始登录流程")

            # 访问首页
            self.logger.debug(f"访问首页: {self.home_url}")
            self.driver.get(self.home_url)
            TimingManager.smart_wait(TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger)

            # 处理年龄验证
            self.logger.debug("开始处理年龄验证")
            if not self.handle_age_verification():
                self.logger.debug("年龄验证处理失败")
                return False

            # 查找并点击登录按钮
            login_selectors = [
                "//button[@type='submit']//em[contains(text(), '登录')]/..",
                "//button[contains(text(), '登录')]",
                "#loginsubmit",
            ]

            login_button = self.element_finder.find_clickable_by_selectors(
                login_selectors
            )
            if not login_button:
                # [DEBUG] 输出当前页面标题与正文片段，便于判断是 Cloudflare 挑战页还是站点异常
                try:
                    page_title = self.driver.title
                    body_text = self.driver.execute_script(
                        "return document.body ? document.body.innerText : '';"
                    ) or ""
                    self.logger.error(
                        f"未找到登录按钮。当前页面标题: '{page_title}'，"
                        f"正文片段(前400): {body_text[:400]}"
                    )
                except Exception as e:
                    self.logger.error(f"未找到登录按钮（页面信息获取失败: {e}）")
                else:
                    return False
                return False

            button_text = login_button.text
            self.logger.debug(f"找到登录按钮，文本: '{button_text}'，准备点击")
            BrowserHelper.safe_click(self.driver, login_button, self.logger)
            TimingManager.smart_wait(TimingManager.NAVIGATION_DELAY, 1.0, self.logger)

            # 等待登录弹窗
            self.logger.debug("等待登录弹窗出现")
            login_popup = self.element_finder.find_by_selectors(
                ["#fwin_login"], timeout=5
            )
            if not login_popup:
                self.logger.warning("未检测到登录弹窗")
            else:
                self.logger.debug("登录弹窗已出现")

            # 填写登录表单
            self.logger.debug("开始填写登录表单")
            if not self.fill_login_form():
                self.logger.debug("登录表单填写失败")
                return False

            # 处理安全提问
            self.logger.debug("处理安全提问")
            if not self.handle_security_question():
                self.logger.warning("安全提问处理失败，继续尝试")

            # 提交登录
            submit_selectors = [
                "#fwin_login button[type='submit']",
                "button[type='submit']",
                "#loginsubmit",
            ]

            submit_button = self.element_finder.find_clickable_by_selectors(
                submit_selectors
            )
            if not submit_button:
                self.logger.error("未找到提交按钮")
                return False

            submit_text = submit_button.text
            self.logger.debug(f"找到提交按钮，文本: '{submit_text}'，准备提交登录")
            BrowserHelper.safe_click(self.driver, submit_button, self.logger)
            TimingManager.adaptive_wait(
                TimingManager.PAGE_LOAD_DELAY, "complex", self.logger
            )

            # 验证登录结果
            self.logger.debug("验证登录结果")
            login_result = self.check_login_status()
            if login_result:
                self.logger.info("登录成功")
                return True
            else:
                # 检查是否是账号锁定
                error_message = self.check_login_error_message()
                if error_message and "密码错误次数过多" in error_message:
                    self.logger.error(f"账号被锁定: {error_message}")
                    # 如果是账号锁定，不要继续重试，直接返回失败
                    raise Exception(f"账号锁定: {error_message}")
                else:
                    self.logger.warning("登录失败")
                    return False

        except Exception as e:
            self.logger.error(f"登录过程出错: {e}")
            return False

    def calculate_math_answer(self, question: str) -> Optional[int]:
        """
        计算数学问题答案

        Args:
            question: 数学问题字符串

        Returns:
            计算结果或None
        """
        try:
            pattern = r"(\d+)\s*([+\-*/])\s*(\d+)"
            match = re.search(pattern, question)

            if not match:
                return None

            num1 = int(match.group(1))
            operator = match.group(2)
            num2 = int(match.group(3))

            operations = {
                "+": lambda x, y: x + y,
                "-": lambda x, y: x - y,
                "*": lambda x, y: x * y,
                "/": lambda x, y: x // y,
            }

            if operator in operations:
                return operations[operator](num1, num2)

            return None

        except Exception:
            return None

    def handle_sign_verification(self) -> bool:
        """
        处理签到验证

        Returns:
            是否处理成功
        """
        try:
            self.logger.debug("开始处理签到验证")
            TimingManager.smart_wait(TimingManager.NAVIGATION_DELAY, 1.0, self.logger)

            # 查找数学问题
            self.logger.debug("查找页面中的数学验证问题")
            question_text = self.driver.execute_script(
                """
                var allText = document.body.innerText;
                var mathPattern = /(\\d+)\\s*[+\\-*/]\\s*(\\d+)\\s*=\\s*\\?/;
                var match = allText.match(mathPattern);
                return match ? match[0] : '';
            """
            )

            if not question_text:
                self.logger.info("未发现验证问题，尝试直接提交")
                # [DEBUG] 输出页面关键信息
                try:
                    body_text = self.driver.execute_script(
                        "return document.body.innerText;"
                    ) or ""
                    self.logger.info(
                        f"[DEBUG] 无验证题时body文本(前1200): {body_text[:1200]}"
                    )
                    for sel in [
                        "form[action*='dd_sign']",
                        "form",
                        "input[name='formhash']",
                        "input[name='secanswer']",
                        "input[id*='secqaa']",
                        "#signform",
                    ]:
                        try:
                            els = self.driver.find_elements("css selector", sel)
                            self.logger.info(
                                f"[DEBUG] 选择器 {sel}: 找到 {len(els)} 个"
                            )
                            if els:
                                self.logger.info(
                                    f"[DEBUG]   {sel} outerHTML: {els[0].get_attribute('outerHTML')[:500]}"
                                )
                        except Exception:
                            pass
                except Exception as e:
                    self.logger.info(f"[DEBUG] 输出页面信息失败: {e}")
                return True

            self.logger.info(f"处理验证问题: {question_text}")
            self.logger.debug(f"检测到数学验证问题: {question_text}")

            answer = self.calculate_math_answer(question_text)

            if answer is None:
                self.logger.error("无法计算答案")
                return False

            self.logger.debug(f"计算出答案: {answer}")

            # 模拟人类思考计算过程
            self.logger.info("模拟人类思考计算过程...")
            self._simulate_thinking_process(answer)

            # 查找答案输入框
            answer_selectors = ['input[name="secanswer"]', 'input[id*="secqaaverify"]']
            answer_input = self.element_finder.find_by_selectors(answer_selectors)

            if answer_input:
                input_name = answer_input.get_attribute("name")
                input_id = answer_input.get_attribute("id")
                self.logger.debug(
                    f"找到答案输入框 - name: '{input_name}', id: '{input_id}'"
                )

                # 人性化输入：模拟真实用户行为
                self.logger.info("开始填入答案...")
                self._humanize_input(answer_input, str(answer))
                self.logger.info(f"已填入答案: {answer}")
                self.logger.debug("答案填写完成")

                # 模拟用户检查答案的过程
                self.logger.info("模拟用户检查答案...")
                TimingManager.smart_wait(1.0, 0.5, self.logger)

                # 查找并点击签到按钮
                self.logger.info("查找签到按钮...")
                submit_button = self._find_submit_button()
                if submit_button:
                    self.logger.info("找到签到按钮，开始模拟人类点击...")
                    # 人性化点击：模拟真实用户行为
                    self._humanize_click(submit_button)
                    self.logger.info("签到按钮点击完成")
                    TimingManager.smart_wait(2.0, 1.0, self.logger)
                    return True
                else:
                    self.logger.error("未找到签到按钮")
                    return False
            else:
                self.logger.error("未找到答案输入框")
                return False

        except Exception as e:
            self.logger.error(f"处理签到验证失败: {e}")
            return False

    def sign_in(self) -> bool:
        """
        执行签到

        Returns:
            是否签到成功
        """
        try:
            self.logger.info("开始签到流程")

            # 返回首页
            self.driver.get(self.home_url)
            TimingManager.smart_wait(TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger)

            # 尝试进入签到页面，最多重试3次
            if not self._navigate_to_signin_page():
                self.logger.error("无法进入签到页面")
                return False

            # 检查签到状态
            signin_status = self._check_signin_status()

            if signin_status == "already_signed":
                self.logger.info("✅ 今日已签到")
                return True
            elif signin_status == "need_signin":
                self.logger.info("检测到未签到状态，开始执行签到")
                # 继续执行签到流程
            else:
                self.logger.error("无法确定签到状态")
                return False

            # 执行签到操作
            self._signin_click_attempts = 0
            return self._solve_gocaptcha_and_signin()

        except Exception as e:
            self.logger.error(f"签到失败: {e}")
            return False

    def _check_signin_status(self) -> str:
        """
        检查签到状态

        Returns:
            "already_signed": 已签到
            "need_signin": 需要签到
            "unknown": 无法确定状态
        """
        try:
            self.logger.debug("检查签到状态，查找签到按钮区域")

            # 先检查是否有系统繁忙提示
            if self._check_system_busy():
                self.logger.warning("检测到系统繁忙，无法确定签到状态")
                return "unknown"

            # 先查找签到按钮区域
            sign_area_selector = "div.ddpc_sign_btna"
            sign_area = self.element_finder.find_by_selectors([sign_area_selector])

            if not sign_area:
                self.logger.warning("未找到签到按钮区域 div.ddpc_sign_btna")
                return "unknown"

            # 获取按钮区域的所有子元素
            buttons = sign_area.find_elements("tag name", "a")

            for button in buttons:
                try:
                    button_class = button.get_attribute("class") or ""
                    button_text = button.text.strip()

                    self.logger.debug(
                        f"检查按钮 - class: '{button_class}', text: '{button_text}'"
                    )

                    # 检查是否是灰色按钮（已签到）
                    if "ddpc_sign_btn_grey" in button_class:
                        if "今日已签到" in button_text:
                            self.logger.info(f"✅ 检测到已签到状态: {button_text}")
                            return "already_signed"

                    # 检查是否是红色按钮（未签到）
                    elif "ddpc_sign_btn_red" in button_class:
                        self.logger.info(f"🔴 检测到未签到状态: {button_text}")
                        return "need_signin"

                except Exception as e:
                    self.logger.debug(f"检查按钮时出错: {e}")
                    continue

            # 如果没有找到明确的按钮状态，返回未知状态
            self.logger.warning("⚠️ 未找到明确的签到按钮状态，返回未知状态")
            return "unknown"

        except Exception as e:
            self.logger.error(f"检查签到状态时出错: {e}")
            return "unknown"

    def _perform_signin_action(self) -> bool:
        """
        执行具体的签到操作

        Returns:
            是否签到成功
        """
        try:
            # 防止按钮点击方式无限重试（_perform_signin_action 与 _verify_signin_success 互相递归）
            self._signin_click_attempts += 1
            if self._signin_click_attempts > 4:
                self.logger.error("签到按钮点击尝试次数超限，停止按钮点击方式")
                return False

            # 扩展签到按钮选择器，支持button和a标签
            sign_button_selectors = [
                # 原有的a标签选择器
                "div.ddpc_sign_btna a.ddpc_sign_btn_red",
                "a.ddpc_sign_btn_red",
                'a[class*="sign_btn"]',
                'a[href*="sign"]',
                # 新增button标签选择器
                'button[name="signsubmit"]',
                'button[type="submit"][name="signsubmit"]',
                'button.pn.pnc[name="signsubmit"]',
                'button[class*="pn"][class*="pnc"]',
                'button[type="submit"]',
                'input[type="submit"][name="signsubmit"]',
                'input[type="button"][name="signsubmit"]',
                # XPath选择器
                '//button[@name="signsubmit"]',
                '//button[@type="submit" and @name="signsubmit"]',
                '//button[contains(@class, "pn") and contains(@class, "pnc")]',
                '//button[contains(text(), "签到")]',
                '//input[@type="submit" and @name="signsubmit"]',
                '//input[@type="button" and @name="signsubmit"]',
            ]

            sign_button = self.element_finder.find_clickable_by_selectors(
                sign_button_selectors
            )
            if not sign_button:
                self.logger.error("未找到可点击的签到按钮")
                return False

            # 检查按钮文本和属性
            button_text = sign_button.text.strip()
            button_class = sign_button.get_attribute("class") or ""
            button_href = sign_button.get_attribute("href") or ""
            button_name = sign_button.get_attribute("name") or ""
            button_type = sign_button.get_attribute("type") or ""
            button_tag = sign_button.tag_name.lower()

            self.logger.debug(
                f"找到签到按钮 - 标签: '{button_tag}', 文本: '{button_text}', "
                f"class: '{button_class}', href: '{button_href}', "
                f"name: '{button_name}', type: '{button_type}'"
            )

            # 确保这是一个有效的签到按钮
            is_valid_button = (
                # 原有的a标签判断
                "ddpc_sign_btn_red" in button_class
                or
                # 新增button标签判断
                button_name == "signsubmit"
                or (button_type == "submit" and button_name == "signsubmit")
                or ("pn" in button_class and "pnc" in button_class)
                or
                # 文本内容判断
                any(keyword in button_text for keyword in ["签到", "点击", "Sign"])
                or
                # href判断
                "sign" in button_href.lower()
            )

            if is_valid_button:
                self.logger.info(
                    f"开始点击签到按钮: '{button_text}' (标签: {button_tag}, name: {button_name})"
                )
                # [DEBUG] 输出签到按钮真实HTML与onclick
                try:
                    outer = self.driver.execute_script(
                        "return arguments[0].outerHTML;", sign_button
                    )
                    self.logger.info(f"[DEBUG] 签到按钮 outerHTML: {outer}")
                    self.logger.info(
                        f"[DEBUG] onclick属性: {sign_button.get_attribute('onclick')}"
                    )
                except Exception as e:
                    self.logger.info(f"[DEBUG] 获取签到按钮HTML失败: {e}")

                BrowserHelper.safe_click(self.driver, sign_button, self.logger)
                TimingManager.smart_wait(
                    TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger
                )

                # [DEBUG] 点击后页面信息 + 处理可能的JS弹窗
                try:
                    self.logger.info(
                        f"[DEBUG] 点击后URL: {self.driver.current_url}"
                    )
                    body_text = self.driver.execute_script(
                        "return document.body.innerText;"
                    ) or ""
                    self.logger.info(
                        f"[DEBUG] 点击后body文本(前1500): {body_text[:1500]}"
                    )
                except Exception as e:
                    self.logger.info(f"[DEBUG] 获取点击后页面信息失败: {e}")
                try:
                    alert = self.driver.switch_to.alert
                    self.logger.info(f"[DEBUG] 检测到JS弹窗: {alert.text}")
                    alert.accept()
                    self.logger.info("[DEBUG] 已接受JS弹窗")
                except Exception:
                    self.logger.info("[DEBUG] 无JS弹窗")

                # 处理签到验证
                if self.handle_sign_verification():
                    # 签到完成后，重新验证签到状态
                    return self._verify_signin_success()
                else:
                    self.logger.error("❌ 签到验证失败")
                    return False
            else:
                self.logger.warning(
                    f"按钮不符合签到条件: '{button_text}' (标签: {button_tag}, name: {button_name})"
                )
                return False

        except Exception as e:
            self.logger.error(f"执行签到操作时出错: {e}")
            return False

    def _perform_direct_signin(self) -> bool:
        """
        直接调用签到接口执行签到

        该站 dd_sign 插件真实签到接口：plugin.php?id=dd_sign&ac=sign_v2
        （JS 中 doSignin() 所调用；验证码通过后由前端调用）
        """
        try:
            self.logger.info("尝试直接调用签到接口")

            # 进入签到页（建立同源上下文）
            self.driver.get(f"{self.base_url}/plugin.php?id=dd_sign:index")
            TimingManager.smart_wait(TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger)

            # 直接调用签到接口，观察服务端是否强制要求验证码
            resp = self.driver.execute_async_script(
                """
                var cb = arguments[arguments.length - 1];
                fetch('plugin.php?id=dd_sign&ac=sign_v2')
                    .then(function(r){ return r.text(); })
                    .then(function(t){ cb(t); })
                    .catch(function(e){ cb('ERR: ' + e); });
                """
            )
            self.logger.info(f"[DEBUG] ac=sign_v2 响应: {resp}")

            if resp and '"code":200' in resp:
                # 接口返回成功，稍等页面刷新后确认签到状态
                TimingManager.smart_wait(3, 1, self.logger)
                self.driver.get(f"{self.base_url}/plugin.php?id=dd_sign:index")
                TimingManager.smart_wait(TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger)
                status = self._check_signin_status()
                if status == "already_signed":
                    self.logger.info("✅ 直接接口签到成功")
                    return True
                self.logger.warning(f"接口返回成功但状态未确认: {status}")
                return False

            self.logger.warning("直接接口未返回成功（服务端可能要求先完成验证码）")
            return False
        except Exception as e:
            self.logger.error(f"直接签到失败: {e}")
            return False

    def _solve_gocaptcha_and_signin(self) -> bool:
        """
        自动处理 GoCaptcha 验证码并完成签到

        该站 dd_sign 插件签到前必须通过 GoCaptcha 验证：
          1. 生成验证码:  GET  misc.php?mod=captcha
          2. 提交校验:    POST misc.php?mod=captcha&action=check  body="x,y"（缺口坐标）
          3. 校验通过后:  GET  plugin.php?id=dd_sign&ac=sign_v2  完成签到
        slide/drag 类型可直接用缺口坐标 POST，无需真实拖拽。
        """
        import json as _json

        try:
            self.logger.info("开始 GoCaptcha 自动处理")

            # 确保在签到页（同源上下文）
            self.driver.get(f"{self.base_url}/plugin.php?id=dd_sign:index")
            TimingManager.smart_wait(TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger)

            # 尝试次数可配置：站点对每日验证码生成次数有限额，
            # 每天最多 5 次，给手动签到至少留 2 次
            max_attempts = int(os.environ.get("CAPTCHA_MAX_ATTEMPTS", "5"))
            for attempt in range(max_attempts):
                try:
                    # 1. 生成验证码
                    cap_raw = self.driver.execute_async_script(
                        """
                        var cb = arguments[arguments.length - 1];
                        fetch('misc.php?mod=captcha')
                            .then(function(r){ return r.json(); })
                            .then(function(j){ cb(JSON.stringify(j)); })
                            .catch(function(e){ cb('ERR:' + e); });
                        """
                    )
                    if not cap_raw or cap_raw.startswith("ERR"):
                        self.logger.warning(f"获取验证码失败: {cap_raw}")
                        break
                    self.logger.info(f"[DEBUG] 验证码原始响应(前1500): {cap_raw[:1500]}")
                    cap = _json.loads(cap_raw)
                    data = cap.get("data") or {}
                    ctype = data.get("type", "")
                    self.logger.info(f"验证码类型: {ctype} (第{attempt + 1}次)")

                    master_b64 = data.get("master_image_base64", "")
                    thumb_b64 = data.get("thumb_image_base64", "")
                    display_x = data.get("display_x")
                    display_y = data.get("display_y")
                    self.logger.debug(
                        f"背景图base64长度: {len(master_b64)}, "
                        f"拼图块base64长度: {len(thumb_b64)}, "
                        f"display_x: {display_x}, display_y: {display_y}"
                    )

                    # 保存验证码图片到 logs/captcha/ 供离线校准识别算法
                    try:
                        self._dump_captcha_images(
                            ctype, attempt, master_b64, thumb_b64
                        )
                    except Exception as e:
                        self.logger.debug(f"保存验证码图片失败: {e}")

                    if ctype in ("slide", "drag"):
                        from ..utils.gocaptcha_solver import detect_gap

                        gap = detect_gap(master_b64, thumb_b64)
                        if not gap:
                            self.logger.warning("缺口识别失败，重试")
                            TimingManager.smart_wait(2, 1, self.logger)
                            continue
                        gx, gy, aox, aoy = gap
                        # SlideRegion(drag) 组件 confirm 报告的是 thumb 画布位置，
                        # 服务端答案 = 缺口位置 - 画布内透明偏移（实测 (7,2)）；
                        # Slide 组件报告可见块位置（2026-10-11 实测直接提交缺口坐标可过），
                        # 但为保险起见按次轮换两种语义。
                        if ctype == "drag":
                            value = f"{gx - aox},{gy - aoy}"
                            self.logger.info(
                                f"识别缺口: ({gx},{gy})，alpha偏移: ({aox},{aoy})，"
                                f"提交画布坐标: {value}"
                            )
                        elif attempt % 2 == 1:
                            value = f"{gx - aox},{gy - aoy}"
                            self.logger.info(
                                f"识别缺口: ({gx},{gy})，提交画布坐标: {value}"
                            )
                        else:
                            value = f"{gx},{gy}"
                            self.logger.info(f"识别缺口: ({gx},{gy})，提交绝对坐标: {value}")
                    elif ctype == "click":
                        self.logger.warning("click 类型暂未支持，换一张验证码重试")
                        TimingManager.smart_wait(2, 1, self.logger)
                        continue
                    else:
                        self.logger.warning(f"类型 {ctype} 暂未支持，换一张验证码重试")
                        TimingManager.smart_wait(2, 1, self.logger)
                        continue

                    # 2. 提交校验
                    check = self.driver.execute_async_script(
                        """
                        var cb = arguments[arguments.length - 1];
                        var value = arguments[0];
                        fetch('misc.php?mod=captcha&action=check', {
                            method: 'POST',
                            headers: { 'Content-Type': 'text/plain' },
                            body: value
                        }).then(function(r){ return r.json(); })
                          .then(function(j){ cb(JSON.stringify(j)); })
                          .catch(function(e){ cb('ERR:' + e); });
                        """,
                        value,
                    )
                    self.logger.info(f"校验响应: {check}")
                    if not check or check.startswith("ERR"):
                        continue
                    ck = _json.loads(check)
                    if ck.get("data") != "ok":
                        self.logger.warning(f"验证未通过: {ck.get('message') or ck}")
                        TimingManager.smart_wait(2, 1, self.logger)
                        continue

                    # 3. 校验通过，调用签到接口
                    sign = self.driver.execute_async_script(
                        """
                        var cb = arguments[arguments.length - 1];
                        fetch('plugin.php?id=dd_sign&ac=sign_v2')
                            .then(function(r){ return r.json(); })
                            .then(function(j){ cb(JSON.stringify(j)); })
                            .catch(function(e){ cb('ERR:' + e); });
                        """
                    )
                    self.logger.info(f"签到接口响应: {sign}")
                    if sign and '"code":200' in sign:
                        TimingManager.smart_wait(3, 1, self.logger)
                        self.driver.get(
                            f"{self.base_url}/plugin.php?id=dd_sign:index"
                        )
                        TimingManager.smart_wait(
                            TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger
                        )
                        if self._check_signin_status() == "already_signed":
                            self.logger.info("✅ GoCaptcha 验证 + 签到成功")
                            return True
                        self.logger.warning("接口成功但状态未确认")
                        return False
                    self.logger.warning(f"签到接口未成功: {sign}")
                    return False
                except Exception as e:
                    self.logger.warning(f"GoCaptcha 处理异常: {e}")
                    TimingManager.smart_wait(2, 1, self.logger)

            self.logger.error("GoCaptcha 自动处理多次尝试后仍未成功")
            return False
        except Exception as e:
            self.logger.error(f"GoCaptcha 处理失败: {e}")
            return False

    def _dump_captcha_images(self, ctype, attempt, master_b64, thumb_b64):
        """把验证码图片存到 logs/captcha/，便于离线校准识别算法（随 artifact 上传）"""
        import base64 as _b64
        import os as _os

        out_dir = _os.path.join("logs", "captcha")
        _os.makedirs(out_dir, exist_ok=True)
        for name, b64 in (("master", master_b64), ("thumb", thumb_b64)):
            if not b64:
                continue
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            data = _b64.b64decode(raw)
            ext = "jpg" if "image/jpeg" in b64[:40] else "png"
            path = _os.path.join(out_dir, f"{attempt + 1}_{ctype}_{name}.{ext}")
            with open(path, "wb") as f:
                f.write(data)
        self.logger.debug(f"验证码图片已保存到 {out_dir}")

    def _navigate_to_signin_page(self) -> bool:
        """
        导航到签到页面并验证URL

        Returns:
            是否成功进入签到页面
        """
        for attempt in range(3):
            try:
                self.logger.debug(f"尝试进入签到页面 - 第{attempt + 1}次")

                # 点击签到导航
                sign_nav_selectors = [
                    'a[href="plugin.php?id=dd_sign:index"]',
                    'a[href*="dd_sign"]',
                ]

                sign_nav_link = self.element_finder.find_clickable_by_selectors(
                    sign_nav_selectors
                )
                if not sign_nav_link:
                    self.logger.warning(f"第{attempt + 1}次未找到签到导航链接")
                    continue

                BrowserHelper.safe_click(self.driver, sign_nav_link, self.logger)
                TimingManager.smart_wait(
                    TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger
                )

                # 验证当前URL是否为签到页面
                current_url = self.driver.current_url
                if "plugin.php?id=dd_sign" in current_url:
                    self.logger.info(f"成功进入签到页面: {current_url}")
                    return True
                else:
                    self.logger.warning(
                        f"第{attempt + 1}次未成功进入签到页面，当前URL: {current_url}"
                    )

            except Exception as e:
                self.logger.warning(f"第{attempt + 1}次进入签到页面失败: {e}")

        return False

    def _verify_signin_success(self, max_retries: int = 3) -> bool:
        """
        验证签到是否成功，检测系统繁忙状态并重试
        如果刷新后仍显示未签到，重新执行签到流程

        Args:
            max_retries: 最大重试次数

        Returns:
            是否签到成功
        """
        for attempt in range(max_retries):
            try:
                self.logger.info(f"验证签到状态 (第 {attempt + 1}/{max_retries} 次)")

                # 刷新页面重新检查签到状态
                self.driver.refresh()
                TimingManager.smart_wait(
                    TimingManager.PAGE_LOAD_DELAY, 1.0, self.logger
                )

                # 检查是否有系统繁忙提示
                if self._check_system_busy():
                    self.logger.warning(f"检测到系统繁忙提示 (第 {attempt + 1} 次)")
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 递增等待时间：5秒、10秒、15秒
                        self.logger.info(f"等待 {wait_time} 秒后重试...")
                        TimingManager.smart_wait(wait_time, 1.0, self.logger)
                        continue
                    else:
                        self.logger.error("系统繁忙，重试次数已达上限")
                        return False

                # 重新检查签到状态
                signin_status = self._check_signin_status()

                if signin_status == "already_signed":
                    self.logger.info("✅ 签到验证成功，状态确认已签到")
                    return True
                elif signin_status == "need_signin":
                    self.logger.warning(f"签到状态仍显示未签到 (第 {attempt + 1} 次)")
                    if attempt < max_retries - 1:
                        # 如果仍显示未签到，重新执行签到流程
                        self.logger.info("重新执行签到流程...")
                        wait_time = (attempt + 1) * 2  # 等待时间：2秒、4秒、6秒
                        self.logger.info(f"等待 {wait_time} 秒后重新签到...")
                        TimingManager.smart_wait(wait_time, 1.0, self.logger)

                        # 重新执行签到操作
                        if self._perform_signin_action():
                            self.logger.info("重新签到成功")
                            return True
                        else:
                            self.logger.warning("重新签到失败，继续重试")
                            continue
                    else:
                        self.logger.error("签到验证失败，状态仍显示未签到")
                        return False
                else:
                    self.logger.warning(f"无法确定签到状态 (第 {attempt + 1} 次)")
                    if attempt < max_retries - 1:
                        # 如果无法确定状态，也尝试重新执行签到流程
                        self.logger.info("状态不明确，尝试重新执行签到流程...")
                        wait_time = (attempt + 1) * 2  # 等待时间：2秒、4秒、6秒
                        self.logger.info(f"等待 {wait_time} 秒后重新签到...")
                        TimingManager.smart_wait(wait_time, 1.0, self.logger)

                        # 重新执行签到操作
                        if self._perform_signin_action():
                            self.logger.info("重新签到成功")
                            return True
                        else:
                            self.logger.warning("重新签到失败，继续重试")
                            continue
                    else:
                        self.logger.error("签到验证失败，无法确定状态")
                        return False

            except Exception as e:
                self.logger.error(f"验证签到状态时出错 (第 {attempt + 1} 次): {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    self.logger.info(f"等待 {wait_time} 秒后重试...")
                    TimingManager.smart_wait(wait_time, 1.0, self.logger)
                    continue
                else:
                    self.logger.error("签到验证失败，重试次数已达上限")
                    return False

        return False

    def _check_system_busy(self) -> bool:
        """
        检查页面是否显示系统繁忙提示

        Returns:
            是否检测到系统繁忙
        """
        try:
            # 检查常见的系统繁忙提示文本
            busy_texts = [
                "系统繁忙",
                "请稍等重试",
                "系统繁忙,请稍等重试",
                "服务器繁忙",
                "请稍后再试",
                "系统维护中",
            ]

            page_text = self.driver.page_source.lower()

            for busy_text in busy_texts:
                if busy_text.lower() in page_text:
                    self.logger.debug(f"检测到系统繁忙提示: {busy_text}")
                    return True

            # 检查是否有弹窗提示
            alert_selectors = [".alert", ".message", ".tip", ".warning", ".error"]

            for selector in alert_selectors:
                elements = self.driver.find_elements("css selector", selector)
                for element in elements:
                    element_text = element.text.strip().lower()
                    for busy_text in busy_texts:
                        if busy_text.lower() in element_text:
                            self.logger.debug(
                                f"检测到弹窗中的系统繁忙提示: {busy_text}"
                            )
                            return True

            return False

        except Exception as e:
            self.logger.debug(f"检查系统繁忙状态时出错: {e}")
            return False

    def _find_submit_button(self):
        """
        查找提交按钮

        Returns:
            提交按钮元素或None
        """
        try:
            # 多种提交按钮选择器
            submit_selectors = [
                # 常见的提交按钮
                'button[type="submit"]',
                'input[type="submit"]',
                'button[name="signsubmit"]',
                'input[name="signsubmit"]',
                # 包含提交文本的按钮
                'button:contains("提交")',
                'button:contains("确认")',
                'button:contains("签到")',
                'input[value*="提交"]',
                'input[value*="确认"]',
                'input[value*="签到"]',
                # XPath选择器
                '//button[@type="submit"]',
                '//input[@type="submit"]',
                '//button[contains(text(), "提交")]',
                '//button[contains(text(), "确认")]',
                '//button[contains(text(), "签到")]',
                '//input[@value="提交"]',
                '//input[@value="确认"]',
                '//input[@value="签到"]',
                # 表单提交按钮
                'form button[type="submit"]',
                'form input[type="submit"]',
            ]

            submit_button = self.element_finder.find_clickable_by_selectors(
                submit_selectors
            )

            if submit_button:
                button_text = submit_button.text.strip()
                button_value = submit_button.get_attribute("value") or ""
                button_type = submit_button.get_attribute("type") or ""
                button_name = submit_button.get_attribute("name") or ""

                self.logger.debug(
                    f"找到提交按钮 - 文本: '{button_text}', value: '{button_value}', "
                    f"type: '{button_type}', name: '{button_name}'"
                )

                return submit_button
            else:
                self.logger.warning("未找到提交按钮")
                return None

        except Exception as e:
            self.logger.error(f"查找提交按钮时出错: {e}")
            return None

    def _humanize_input(self, element, text):
        """
        人性化输入：模拟真实用户输入行为

        Args:
            element: 输入框元素
            text: 要输入的文本
        """
        try:
            import random
            import time

            # 先点击输入框，模拟用户行为
            element.click()
            time.sleep(random.uniform(0.1, 0.3))

            # 清空输入框
            element.clear()
            time.sleep(random.uniform(0.1, 0.2))

            # 逐字符输入，模拟真实打字速度
            for char in text:
                element.send_keys(char)
                # 随机延迟，模拟真实打字速度
                time.sleep(random.uniform(0.05, 0.15))

            # 输入完成后稍微等待
            time.sleep(random.uniform(0.2, 0.5))

            self.logger.debug(f"人性化输入完成: {text}")

        except Exception as e:
            self.logger.error(f"人性化输入失败: {e}")
            # 如果人性化输入失败，使用普通输入
            element.clear()
            element.send_keys(text)

    def _humanize_click(self, element):
        """
        人性化点击：模拟真实用户点击行为

        Args:
            element: 要点击的元素
        """
        try:
            import random
            import time
            from selenium.webdriver.common.action_chains import ActionChains

            # 随机等待，模拟用户思考时间
            time.sleep(random.uniform(0.5, 1.5))

            # 滚动到元素可见区域
            self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(random.uniform(0.2, 0.5))

            # 使用ActionChains模拟更自然的鼠标移动和点击
            actions = ActionChains(self.driver)

            # 移动到元素位置
            actions.move_to_element(element)
            time.sleep(random.uniform(0.1, 0.3))

            # 点击元素
            actions.click(element)
            actions.perform()

            self.logger.debug("人性化点击完成")

        except Exception as e:
            self.logger.error(f"人性化点击失败: {e}")
            # 如果人性化点击失败，使用普通点击
            BrowserHelper.safe_click(self.driver, element, self.logger)

    def _humanize_page_interaction(self):
        """
        人性化页面交互：模拟真实用户浏览行为
        """
        try:
            import random
            import time

            # 随机滚动页面，模拟用户浏览
            scroll_amount = random.randint(100, 500)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            time.sleep(random.uniform(0.5, 1.0))

            # 随机等待，模拟用户阅读时间
            time.sleep(random.uniform(1.0, 3.0))

            self.logger.debug("人性化页面交互完成")

        except Exception as e:
            self.logger.error(f"人性化页面交互失败: {e}")

    def _simulate_human_behavior(self):
        """
        模拟人类行为：随机延迟和交互
        """
        try:
            import random
            import time

            # 随机等待时间，模拟用户思考
            wait_time = random.uniform(1.0, 3.0)
            self.logger.debug(f"模拟人类行为，等待 {wait_time:.2f} 秒")
            time.sleep(wait_time)

            # 随机页面交互
            if random.random() < 0.3:  # 30%概率进行页面交互
                self._humanize_page_interaction()

        except Exception as e:
            self.logger.error(f"模拟人类行为失败: {e}")

    def _simulate_thinking_process(self, answer):
        """
        模拟人类思考计算过程

        Args:
            answer: 计算出的答案
        """
        try:
            import random
            import time

            # 模拟看到题目后的思考时间
            self.logger.debug("模拟用户看到题目，开始思考...")
            thinking_time = random.uniform(2.0, 4.0)
            time.sleep(thinking_time)

            # 模拟计算过程（根据答案复杂度调整时间）
            if isinstance(answer, (int, float)):
                if answer < 10:
                    calc_time = random.uniform(1.0, 2.0)
                elif answer < 100:
                    calc_time = random.uniform(2.0, 3.5)
                else:
                    calc_time = random.uniform(3.0, 5.0)
            else:
                calc_time = random.uniform(1.5, 2.5)

            self.logger.debug(f"模拟用户计算过程，耗时 {calc_time:.2f} 秒")
            time.sleep(calc_time)

            # 模拟确认答案的过程
            self.logger.debug("模拟用户确认答案...")
            confirm_time = random.uniform(0.5, 1.5)
            time.sleep(confirm_time)

            # 模拟准备输入的状态
            self.logger.debug("模拟用户准备输入答案...")
            prep_time = random.uniform(0.3, 0.8)
            time.sleep(prep_time)

            self.logger.info(f"思考计算完成，准备输入答案: {answer}")

        except Exception as e:
            self.logger.error(f"模拟思考过程失败: {e}")
            # 如果模拟失败，至少等待一下
            time.sleep(random.uniform(1.0, 2.0))
