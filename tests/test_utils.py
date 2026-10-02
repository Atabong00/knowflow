import pytest
from app.utils import slugify, Paginator


class TestSlugify:
    def test_basic_slugify(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("VPN & Firewall Guide!") == "vpn-firewall-guide"

    def test_multiple_hyphens(self):
        assert slugify("Test---Multiple---Hyphens") == "test-multiple-hyphens"

    def test_leading_trailing_hyphens(self):
        assert slugify("-Leading and Trailing-") == "leading-and-trailing"

    def test_empty_string(self):
        assert slugify("") == ""


class TestPaginator:
    def test_pagination_basic(self):
        items = list(range(1, 26))  # 25 items
        paginator = Paginator(page=1, per_page=10)
        result = paginator.paginate(type("Query", (), {
            "count": lambda self: 25,
            "offset": lambda self, x: type("Query2", (), {
                "limit": lambda self, y: type("Query3", (), {
                    "all": lambda self: items[:y]
                })()
            })(),
            "order_by": lambda self: None
        })())
        
        assert result["total"] == 25
        assert result["page"] == 1
        assert result["total_pages"] == 3
        assert result["has_next"] is True
        assert result["has_prev"] is False

    def test_pagination_last_page(self):
        items = list(range(1, 26))
        paginator = Paginator(page=3, per_page=10)
        result = paginator.paginate(type("Query", (), {
            "count": lambda self: 25,
            "offset": lambda self, x: type("Query2", (), {
                "limit": lambda self, y: type("Query3", (), {
                    "all": lambda self: items[20:20+y]
                })()
            })(),
            "order_by": lambda self: None
        })())
        
        assert result["total_pages"] == 3
        assert result["has_next"] is False
        assert result["has_prev"] is True
