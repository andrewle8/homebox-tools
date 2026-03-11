from homebox_tools.lib.name_cleaner import clean_name


def test_strips_excessive_description():
    raw = "ASUS ROG Rapture WiFi 6E Gaming Router (GT-AXE16000) - Quad-Band, 6 GHz Ready, Dual 10G Ports, Triple-Level Game Acceleration, 2.5G WAN Port, AiMesh Compatible, Lifetime Internet Security"
    result = clean_name(raw)
    assert "ASUS" in result or "Asus" in result
    assert "GT-AXE16000" in result
    assert "Lifetime Internet Security" not in result
    assert len(result) < 80


def test_fixes_all_caps_brand():
    raw = "SAMSUNG 990 PRO SSD 2TB PCIe 4.0 M.2 2280 Internal Solid State Hard Drive, Seq. Read Speeds Up to 7,450 MB/s for High End Computing, Workstations, Compatible with Playstation 5 - MZ-V9P2T0B/AM"
    result = clean_name(raw)
    assert result.startswith("Samsung")
    assert "990 PRO" in result
    assert "Compatible with Playstation" not in result


def test_removes_seo_suffix():
    raw = "Anker USB C Charger 40W, 521 Charger (Nano Pro), PIQ 3.0 Durable Compact Fast Charger for iPhone 15/15 Pro/14/13/12, Galaxy, Pixel, iPad (Cable Not Included) - White"
    result = clean_name(raw)
    assert "Anker" in result
    assert len(result) < len(raw)


def test_preserves_short_clean_name():
    raw = "Apple AirPods Pro (2nd Generation)"
    result = clean_name(raw)
    assert result == "Apple AirPods Pro (2nd Generation)"


def test_strips_whitespace():
    raw = "  Some Product   Name  "
    result = clean_name(raw)
    assert result == result.strip()
    assert "  " not in result


def test_removes_trailing_color():
    raw = "Logitech MX Master 3S - Wireless Performance Mouse with Ultra-Fast Scrolling, Ergo, 8K DPI, Track on Glass, Quiet Clicks, USB-C, Bluetooth, Windows, Linux, Chrome - Graphite"
    result = clean_name(raw)
    assert "Graphite" not in result


def test_handles_model_in_parens():
    raw = "TP-Link AX1800 WiFi 6 Router (Archer AX21) - Dual Band Wireless Internet Router, Gigabit Router, USB Port, Works with Alexa - A Certified for Humans Device"
    result = clean_name(raw)
    assert "TP-Link" in result
    assert "Certified for Humans" not in result


def test_comma_separated_feature_list():
    raw = "Kasa Smart Plug Power Strip HS300, Surge Protector with 6 Individually Controlled Smart Outlets and 3 USB Ports"
    result = clean_name(raw)
    assert "Kasa" in result
    assert "HS300" in result
    assert "Surge Protector" not in result
    assert len(result) < 60


def test_apc_ups_long_title():
    raw = "APC UPS 600VA / 330W UPS Battery Backup & Surge Protector, 7 Outlets (NEMA 5-15R), USB Charging Port, BE600M1 Uninterruptible Power Supply for Computers, Wi-Fi Routers, and Home Office Electronics"
    result = clean_name(raw)
    assert "APC" in result
    assert len(result) < 80


# --- New tests for paren-then-dash model number handling ---

def test_paren_model_then_dash_cuts_after_paren():
    raw = "TP-Link AX1800 WiFi 6 Router (Archer AX21) - Dual Band Wireless Internet Router"
    result = clean_name(raw)
    assert "TP-Link" in result
    assert "(Archer AX21)" in result
    assert "Dual Band" not in result


def test_paren_model_then_dash_preserves_short_names():
    raw = "Apple AirPods Pro (2nd Generation)"
    result = clean_name(raw)
    assert result == "Apple AirPods Pro (2nd Generation)"


def test_paren_model_then_dash_netgear():
    raw = "NETGEAR Nighthawk WiFi 6 Router (RAX50) - AX5400 Dual Band Wireless Speed"
    result = clean_name(raw)
    assert "Netgear" in result or "NETGEAR" in result
    assert "(RAX50)" in result
    assert "Dual Band" not in result


# --- New tests for additional SEO cutoff patterns ---

def test_ideal_for_cutoff():
    raw = "USB-C Hub Multiport Adapter 7-in-1 Docking Station, Ideal for Home Office Setup"
    result = clean_name(raw)
    assert "hub" in result.lower()
    assert "Ideal for" not in result


def test_great_for_cutoff():
    raw = "Wireless Mechanical Keyboard RGB Backlit Full Size, Great for Gaming and Productivity"
    result = clean_name(raw)
    assert "Wireless Mechanical Keyboard" in result
    assert "Great for" not in result


def test_perfect_for_cutoff():
    raw = "Portable Bluetooth Speaker Waterproof IPX7, Perfect for Outdoor Adventures and Beach"
    result = clean_name(raw)
    assert "Portable Bluetooth Speaker" in result
    assert "Perfect for" not in result


def test_designed_for_cutoff():
    raw = "Ergonomic Office Chair with Lumbar Support Mesh Back, Designed for Long Hours of Comfortable Sitting"
    result = clean_name(raw)
    assert "Ergonomic Office Chair" in result
    assert "Designed for" not in result


def test_best_for_cutoff():
    raw = "4K Webcam with Ring Light and Microphone, Best for Video Calls and Streaming"
    result = clean_name(raw)
    assert "4K Webcam" in result
    assert "Best for" not in result


# --- New tests for leading bracket tag stripping ---

def test_strips_leading_updated_bracket():
    raw = "[Updated 2024] TP-Link AX1800 WiFi 6 Router"
    result = clean_name(raw)
    assert result.startswith("TP-Link")
    assert "[Updated 2024]" not in result


def test_strips_leading_pack_bracket():
    raw = "[2 Pack] USB C Cable Fast Charging 6ft"
    result = clean_name(raw)
    assert result.startswith("USB")
    assert "[2 Pack]" not in result


def test_strips_multiple_leading_brackets():
    raw = "[2024 Upgrade] [Premium] Bluetooth Headphones Over Ear"
    result = clean_name(raw)
    assert result.startswith("Bluetooth")
    assert "[2024 Upgrade]" not in result
    assert "[Premium]" not in result


def test_does_not_strip_mid_title_brackets():
    raw = "Apple AirPods Pro [2nd Generation] Wireless Earbuds"
    result = clean_name(raw)
    assert "[2nd Generation]" in result
