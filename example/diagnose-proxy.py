#!/usr/bin/env python3
"""
代理诊断工具 - 完整验证代理配置是否生效
"""
import sys
import requests
import time

def test_direct_connection():
    """测试直连（不使用代理）"""
    print("\n" + "="*60)
    print("步骤 1: 测试直连（不使用代理）")
    print("="*60)

    try:
        start = time.time()
        response = requests.get(
            'https://api.ipify.org?format=json',
            timeout=10
        )
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            print(f"✅ 直连成功")
            print(f"   出口 IP: {data['ip']}")
            print(f"   延迟: {elapsed:.0f}ms")
            return data['ip']
        else:
            print(f"❌ HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ 直连失败: {e}")
        return None

def test_with_proxy(proxy_url):
    """测试使用代理"""
    print("\n" + "="*60)
    print(f"步骤 2: 测试代理连接")
    print(f"代理地址: {proxy_url}")
    print("="*60)

    proxies = {
        'http': proxy_url,
        'https': proxy_url
    }

    try:
        # 测试 1: 检查出口 IP
        print("\n🔍 测试 2.1: 检查出口 IP")
        start = time.time()
        response = requests.get(
            'https://api.ipify.org?format=json',
            proxies=proxies,
            timeout=10
        )
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ 成功! 出口 IP: {data['ip']}")
            print(f"   ⏱️  延迟: {elapsed:.0f}ms")
            proxy_ip = data['ip']
        else:
            print(f"   ❌ HTTP {response.status_code}")
            return False

        # 测试 2: 多次请求验证代理稳定性
        print("\n🔍 测试 2.2: 验证代理稳定性（5次请求）")
        for i in range(5):
            try:
                start = time.time()
                response = requests.get(
                    'https://httpbin.org/ip',
                    proxies=proxies,
                    timeout=10
                )
                elapsed = (time.time() - start) * 1000

                if response.status_code == 200:
                    print(f"   请求 {i+1}/5: ✅ 成功 ({elapsed:.0f}ms)")
                else:
                    print(f"   请求 {i+1}/5: ❌ HTTP {response.status_code}")
            except Exception as e:
                print(f"   请求 {i+1}/5: ❌ 失败 - {str(e)[:50]}")

            time.sleep(0.5)

        # 测试 3: 访问 Stripe API（实际场景）
        print("\n🔍 测试 2.3: 访问 Stripe API")
        try:
            start = time.time()
            response = requests.get(
                'https://api.stripe.com/healthcheck',
                proxies=proxies,
                timeout=10
            )
            elapsed = (time.time() - start) * 1000

            if response.status_code in [200, 405]:  # 405 也算正常
                print(f"   ✅ Stripe API 可访问 (HTTP {response.status_code}, {elapsed:.0f}ms)")
            else:
                print(f"   ⚠️  HTTP {response.status_code} ({elapsed:.0f}ms)")
        except Exception as e:
            print(f"   ❌ 失败: {str(e)[:50]}")

        return proxy_ip

    except Exception as e:
        print(f"\n❌ 代理连接失败: {e}")
        print(f"\n可能的原因:")
        print(f"  1. 代理服务器未运行")
        print(f"  2. 代理地址或端口错误")
        print(f"  3. 缺少 PySocks 库（SOCKS5 需要）")
        print(f"  4. 防火墙阻止连接")
        return False

def compare_results(direct_ip, proxy_ip):
    """对比直连和代理的结果"""
    print("\n" + "="*60)
    print("步骤 3: 结果对比")
    print("="*60)

    if not direct_ip or not proxy_ip:
        print("⚠️  无法对比：某个测试失败")
        return

    print(f"\n直连 IP:   {direct_ip}")
    print(f"代理 IP:   {proxy_ip}")

    if direct_ip == proxy_ip:
        print("\n🔴 警告：两个 IP 相同！")
        print("   这意味着代理没有生效，请求走了直连。")
        print("\n可能的原因:")
        print("  1. requests 库无法连接到代理，静默回退到直连")
        print("  2. Docker 容器无法访问宿主机的代理端口")
        print("  3. SOCKS5 需要 PySocks 库，但未安装")
        print("\n解决方案:")
        print("  - 如果是 Docker 环境，使用 host.docker.internal 替代 IP")
        print("  - 安装 PySocks: pip install pysocks --break-system-packages")
        print("  - 检查防火墙设置")
    else:
        print("\n🟢 成功：代理已生效！")
        print("   出口 IP 不同，说明请求确实通过了代理。")

def main():
    if len(sys.argv) < 2:
        print("用法: python diagnose-proxy.py <proxy_url>")
        print("\n示例:")
        print("  python diagnose-proxy.py socks5://192.168.67.148:7080")
        print("  python diagnose-proxy.py http://127.0.0.1:7890")
        sys.exit(1)

    proxy_url = sys.argv[1]

    print("\n" + "="*60)
    print("代理诊断工具")
    print("="*60)
    print(f"\n测试代理: {proxy_url}")

    # 步骤 1: 测试直连
    direct_ip = test_direct_connection()

    # 步骤 2: 测试代理
    proxy_ip = test_with_proxy(proxy_url)

    # 步骤 3: 对比结果
    compare_results(direct_ip, proxy_ip)

    print("\n" + "="*60)
    print("诊断完成")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
