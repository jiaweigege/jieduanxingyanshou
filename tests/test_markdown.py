from app.routes import render_markdown


def test_gfm_features_render():
    source = """
# Title

| A | B |
|---|---|
| 1 | 2 |

```python
print("hello")
```

- [x] done
- [ ] todo

https://example.com
"""
    html = render_markdown(source)
    assert "<table>" in html
    assert "<pre" in html
    assert "checkbox" in html
    assert "https://example.com" in html


def test_untrusted_script_is_removed():
    html = render_markdown("<script>alert(1)</script>")
    assert "<script>" not in html
