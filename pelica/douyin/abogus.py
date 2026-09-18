# 本文件为第三方逆向实现，来源：https://github.com/amxsa/douyin_abogus_python
# 用于生成抖音 web 接口的 a_bogus 签名参数。仅本地个人使用，版权归原作者所有。
# 若接口签名算法更新，需要同步更新此文件（社区通常跟进较快）。
from random import choice
from random import randint
from random import random
from time import time
from urllib.parse import urlencode

from gmssl import sm3, func


class ABogus:
    __end_string = "cus"
    __str = {
        "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
        "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
        "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
    }

    def __init__(self, user_agent: str = "", platform: str = None):
        self.user_agent = user_agent
        self.ua_code = self.generate_ua_code(user_agent)
        self.browser = self.generate_browser_info(platform)
        self.browser_len = len(self.browser)
        self.browser_code = self.char_code_at(self.browser)

    def generate_ua_code(self, user_agent: str) -> list:
        numbers = [0.00390625, 1, 14]
        key_string = ''.join(chr(int(num)) for num in numbers)
        return self.sm3_to_array(self.generate_result(self.rc4_encrypt(user_agent, key_string), "s3"))

    def list_1(self, a=170, b=85, c=45) -> list:
        return self.random_list(a, b, 1, 2, 5, c & a)

    def list_2(self, a=170, b=85) -> list:
        return self.random_list(a, b, 1, 0, 0, 0)

    def list_3(self, a=170, b=85) -> list:
        return self.random_list(a, b, 1, 0, 5, 0)

    def random_list(self, b=170, c=85, d=0, e=0, f=0, g=0) -> list:
        r = random() * 10000
        v = [r, int(r) & 255, int(r) >> 8]
        s = v[1] & b | d
        v.append(s)
        s = v[1] & c | e
        v.append(s)
        s = v[2] & b | f
        v.append(s)
        s = v[2] & c | g
        v.append(s)
        return v[-4:]

    def from_char_code(self, *args):
        return "".join(chr(code) for code in args)

    def generate_string_1(self):
        return self.from_char_code(*self.list_1()) + self.from_char_code(
            *self.list_2()) + self.from_char_code(*self.list_3())

    def generate_string_2(self, url_params: str, method="GET") -> str:
        a = self.generate_string_2_list(url_params, method)
        e = self.end_check_num(a)
        a.extend(self.browser_code)
        a.append(e)
        return self.rc4_encrypt(self.from_char_code(*a), "y")

    def generate_string_2_list(self, url_params: str, method="GET") -> list:
        start_time = int(time() * 1000)
        end_time = start_time + randint(4, 8)
        params_array = self.generate_params_code(url_params)
        method_array = self.generate_method_code(method)
        return self.list_4(
            (end_time >> 24) & 255,
            params_array[21],
            self.ua_code[23],
            (end_time >> 16) & 255,
            params_array[22],
            self.ua_code[24],
            (end_time >> 8) & 255,
            (end_time >> 0) & 255,
            (start_time >> 24) & 255,
            (start_time >> 16) & 255,
            (start_time >> 8) & 255,
            (start_time >> 0) & 255,
            method_array[21],
            method_array[22],
            int(end_time / 256 / 256 / 256 / 256) >> 0,
            int(start_time / 256 / 256 / 256 / 256) >> 0,
            self.browser_len,
        )

    def list_4(self,
               a: int,
               b: int,
               c: int,
               d: int,
               e: int,
               f: int,
               g: int,
               h: int,
               i: int,
               j: int,
               k: int,
               m: int,
               n: int,
               o: int,
               p: int,
               q: int,
               r: int,
               ) -> list:
        return [
            44,
            a,
            0,
            0,
            0,
            0,
            24,
            b,
            n,
            0,
            c,
            d,
            0,
            0,
            0,
            1,
            0,
            239,
            e,
            o,
            f,
            g,
            0,
            0,
            0,
            0,
            h,
            0,
            0,
            14,
            i,
            j,
            0,
            k,
            m,
            3,
            p,
            1,
            q,
            1,
            r,
            0,
            0,
            0]

    def end_check_num(self, a: list):
        r = 0
        for i in a:
            r ^= i
        return r

    def convert_to_char_code(self, a):
        d = []
        for i in a:
            d.append(ord(i))
        return d

    def split_array(self, arr, chunk_size=64):
        result = []
        for i in range(0, len(arr), chunk_size):
            result.append(arr[i:i + chunk_size])
        return result

    def char_code_at(self, s):
        return [ord(char) for char in s]

    def generate_result(self, s, e="s4"):
        r = []

        for i in range(0, len(s), 3):
            if i + 2 < len(s):
                n = (
                        (ord(s[i]) << 16)
                        | (ord(s[i + 1]) << 8)
                        | ord(s[i + 2])
                )
            elif i + 1 < len(s):
                n = (ord(s[i]) << 16) | (
                        ord(s[i + 1]) << 8
                )
            else:
                n = ord(s[i]) << 16

            for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
                if j == 6 and i + 1 >= len(s):
                    break
                if j == 0 and i + 2 >= len(s):
                    break
                r.append(self.__str[e][(n & k) >> j])

        r.append("=" * ((4 - len(r) % 4) % 4))
        return "".join(r)

    def generate_method_code(self, method: str = "GET") -> list[int]:
        return self.sm3_to_array(self.sm3_to_array(method + self.__end_string))

    def generate_params_code(self, params: str) -> list[int]:
        return self.sm3_to_array(self.sm3_to_array(params + self.__end_string))

    def sm3_to_array(self, data: str | list) -> list[int]:
        if isinstance(data, str):
            b = data.encode("utf-8")
        else:
            b = bytes(data)  # 将 List[int] 转换为字节数组

        # 将字节数组转换为适合 sm3.sm3_hash 函数处理的列表格式
        h = sm3.sm3_hash(func.bytes_to_list(b))

        # 将十六进制字符串结果转换为十进制整数列表
        return [int(h[i: i + 2], 16) for i in range(0, len(h), 2)]

    def generate_browser_info(self, platform: str = "Win32") -> str:
        inner_width = randint(1280, 1920)
        inner_height = randint(720, 1080)
        outer_width = randint(inner_width, 1920)
        outer_height = randint(inner_height, 1080)
        screen_x = 0
        screen_y = choice((0, 30))
        value_list = [
            inner_width,
            inner_height,
            outer_width,
            outer_height,
            screen_x,
            screen_y,
            0,
            0,
            outer_width,
            outer_height,
            outer_width,
            outer_height,
            inner_width,
            inner_height,
            24,
            24,
            platform,
        ]
        return "|".join(str(i) for i in value_list)

    def rc4_encrypt(self, plaintext, key):
        s = list(range(256))
        j = 0

        for i in range(256):
            j = (j + s[i] + ord(key[i % len(key)])) % 256
            s[i], s[j] = s[j], s[i]

        i = 0
        j = 0
        cipher = []

        for k in range(len(plaintext)):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            t = (s[i] + s[j]) % 256
            cipher.append(chr(s[t] ^ ord(plaintext[k])))

        return ''.join(cipher)

    def generate_a_bogus(self, url_params: dict | str) -> str:
        string_1 = self.generate_string_1()
        string_2 = self.generate_string_2(urlencode(url_params))
        string = string_1 + string_2
        return self.generate_result(string, "s4")


if __name__ == "__main__":
    import requests

    url = "https://www.douyin.com/aweme/v1/web/comment/list/"

    headers = {
        'user-agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        'Cookie': "fpk1=U2FsdGVkX186CR89ZXpoAMmaWzl1I0OMzLbd3k5Ke+zaxHQzUtWTcdL0dTi909o5Er88gKdm/0UEPDw/M7fxoQ==; fpk2=10f9287deaf609ee36fb37783f2b89c0; MONITOR_WEB_ID=e5bc01c8-6fda-4f9f-9bcc-811b865bdfdf; dy_swidth=1440; dy_sheight=900; s_v_web_id=verify_lyo3vs0m_FPkMVLtG_qXLO_4izH_AKGe_AAcvwnBlgReR; xgplayer_user_id=958949402679; passport_csrf_token=0df014450ec1230ed78dd3a462c1d111; passport_csrf_token_default=0df014450ec1230ed78dd3a462c1d111; bd_ticket_guard_client_web_domain=2; d_ticket=d98fc4f96cad7361fa798e99a7f3a7b79b395; n_mh=9-mIeuD4wZnlYrrOvfzG3MuT6aQmCUtmr8FxV8Kl8xY; _bd_ticket_crypt_doamin=2; __security_server_data_status=1; UIFID=96cd3b166f3029d7c1cc3f64582454ab8a83ff1f9e6d6689076dd47ef1dca5f8ff0fa73d12fd1a4324d25e9f7616090a09d42a755a3dd58ad357d4e256935cb12f596f69b1c22ab17ea36abb7558840138089ffdca33cc52237735670a6d099dbcede8982a67db8b45bdf63b17129f95a84dd2695dcfd4538bfb150671290e0e4d286b737c33e98642c28e0bee8c28a1c336c12e63cdb779c7216706477a3ac0; store-region=cn-gd; store-region-src=uid; SEARCH_RESULT_LIST_TYPE=%22single%22; publish_badge_show_info=%220%2C0%2C0%2C1723771427502%22; passport_assist_user=ClCArZPxkLDO5hTV1M1bAwKc87R-3eRHbX1p1IMaj1FH7XXF3g3Xx5qSZCyF93J_BqrPCzLQx9TUOncE0kUNNCLa2Mq545ojGmOfLV9gMFp-PhpKCjzM9w7qj9ibK1x7pO4CJOgB1Q0V8q8adbZIN0YvE00r2G3bogNmsXso9NdlTZoQHmbIfVC5Bx_c8r5Cgc8Q1ubZDRiJr9ZUIAEiAQNbvhaG; sso_uid_tt=5648e665286473d9312555c786e8b938; sso_uid_tt_ss=5648e665286473d9312555c786e8b938; toutiao_sso_user=7c249d923596e82e13b91c32259cb3ac; toutiao_sso_user_ss=7c249d923596e82e13b91c32259cb3ac; sid_ucp_sso_v1=1.0.0-KDNiZTJhNTlkZTUwOGNiOWEyMjMyYWJiNThjNzNjZWEzZDA1MGUwNzUKIQiZn8CP_cyJBhCUrYy2BhjaFiAMMP6-9LMGOAZA9AdIBhoCbHEiIDdjMjQ5ZDkyMzU5NmU4MmUxM2I5MWMzMjI1OWNiM2Fj; ssid_ucp_sso_v1=1.0.0-KDNiZTJhNTlkZTUwOGNiOWEyMjMyYWJiNThjNzNjZWEzZDA1MGUwNzUKIQiZn8CP_cyJBhCUrYy2BhjaFiAMMP6-9LMGOAZA9AdIBhoCbHEiIDdjMjQ5ZDkyMzU5NmU4MmUxM2I5MWMzMjI1OWNiM2Fj; passport_auth_status=3f7bdeb34204c6b6c768f312167ff14e%2C7b30a36bea0b1b8bd4f22a7cb91c5fc9; passport_auth_status_ss=3f7bdeb34204c6b6c768f312167ff14e%2C7b30a36bea0b1b8bd4f22a7cb91c5fc9; uid_tt=8e505222f0ab11f3b95d4eacf1758cb9; uid_tt_ss=8e505222f0ab11f3b95d4eacf1758cb9; sid_tt=2412b0382070af41fee91e8674dac441; sessionid=2412b0382070af41fee91e8674dac441; sessionid_ss=2412b0382070af41fee91e8674dac441; is_staff_user=false; _bd_ticket_crypt_cookie=5946528a7bdbcbefa304ee84c4404c6d; sid_guard=2412b0382070af41fee91e8674dac441%7C1724061337%7C5183998%7CFri%2C+18-Oct-2024+09%3A55%3A35+GMT; sid_ucp_v1=1.0.0-KDJlN2MzNjVlZDJlZDYyMGJlYTQ1NTJiZmRlOWU5NDE0MTdjZDI0NjcKGwiZn8CP_cyJBhCZrYy2BhjaFiAMOAZA9AdIBBoCaGwiIDI0MTJiMDM4MjA3MGFmNDFmZWU5MWU4Njc0ZGFjNDQx; ssid_ucp_v1=1.0.0-KDJlN2MzNjVlZDJlZDYyMGJlYTQ1NTJiZmRlOWU5NDE0MTdjZDI0NjcKGwiZn8CP_cyJBhCZrYy2BhjaFiAMOAZA9AdIBBoCaGwiIDI0MTJiMDM4MjA3MGFmNDFmZWU5MWU4Njc0ZGFjNDQx; download_guide=%223%2F20240819%2F0%22; pwa2=%220%7C0%7C3%7C0%22; strategyABtestKey=%221724127823.468%22; live_use_vvc=%22false%22; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.916%7D; WallpaperGuide=%7B%22showTime%22%3A1724064333265%2C%22closeTime%22%3A0%2C%22showCount%22%3A1%2C%22cursor1%22%3A28%2C%22cursor2%22%3A0%7D; xgplayer_device_id=63734066109; ttwid=1%7C0AN03LaYH76stp4N3B4bDKz38WwE4CxtKAWIZQqtY6Q%7C1724159187%7C51ea6b5b3f0bf1b76c0e457981383ef33cfc4fb7522936d941ffd610f7b497c5; __ac_nonce=066c4951400b80971a26d; __ac_signature=_02B4Z6wo00f01jgfO1QAAIDBauAbTNbav-o4Pz.AAOjRde; douyin.com; xg_device_score=6.582795705874107; device_web_cpu_core=8; device_web_memory_size=8; IsDouyinActive=true; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1440%2C%5C%22screen_height%5C%22%3A900%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A8%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A150%7D%22; csrf_session_id=afc079389b055789ba0f12848acfd3ac; FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAAEoxCnzxeQ2fa7kU_dR1hd9DpO0JhZUsvylhN2HCipPccgJhmy1R-GjDYepR4MPE6%2F1724169600000%2F0%2F0%2F1724159855456%22; FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAAEoxCnzxeQ2fa7kU_dR1hd9DpO0JhZUsvylhN2HCipPccgJhmy1R-GjDYepR4MPE6%2F1724169600000%2F0%2F0%2F1724160455457%22; stream_player_status_params=%22%7B%5C%22is_auto_play%5C%22%3A1%2C%5C%22is_full_screen%5C%22%3A0%2C%5C%22is_full_webscreen%5C%22%3A0%2C%5C%22is_mute%5C%22%3A0%2C%5C%22is_speed%5C%22%3A1%2C%5C%22is_visible%5C%22%3A1%7D%22; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCT21wSldjcjdzNUpjRnRiSWdJQjdrZ05xVTg5MEZseWkvR3kvRzNDZnQyY09laGVaM3BoTy95OFNEckREVFBrYmxrdHFNeHA5T3NYeHZsb2R4TCtoc3M9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoxfQ%3D%3D; passport_fe_beating_status=true; home_can_add_dy_2_desktop=%221%22; odin_tt=a7df12e8c1da1ce62eb9af6ebd3a8c3ec4d1ea769e22440ae984414db4d32305e88c73a5df358818687b608c2d1b2dfc"
    }

    params = {
        "aweme_id": "7400044629845970202",
        "cursor": "0",
        "count": "20",
    }

    bogus = ABogus(headers['user-agent'])

    a_bogus = bogus.generate_a_bogus(params)
    print(a_bogus)

    params['a_bogus'] = a_bogus
    response = requests.get(url, params=params, headers=headers)

    print(response.text)

    user_agent_11 = "Mozilla/5.0"
    print(bogus.generate_ua_code(user_agent_11))
