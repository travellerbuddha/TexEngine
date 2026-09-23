"""Pure tests: what an upload is decided by its bytes, never its name (G-83)."""

import struct
import unittest
import zlib

from kamra.tex.security import filetypes as ft


def _png() -> bytes:
	def chunk(kind: bytes, data: bytes) -> bytes:
		return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

	ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
	return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
	        + chunk(b"IEND", b""))


class TestSniffing(unittest.TestCase):
	def test_images_are_known_by_their_magic_bytes(self):
		self.assertEqual(ft.sniff_image(_png()), "png")
		self.assertEqual(ft.sniff_image(b"\xff\xd8\xff\xe0" + b"\0" * 20), "jpeg")
		self.assertEqual(ft.sniff_image(b"GIF89a" + b"\0" * 20), "gif")
		self.assertEqual(ft.sniff_image(b"GIF87a" + b"\0" * 20), "gif")
		self.assertEqual(ft.sniff_image(b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\0" * 20), "webp")

	def test_markup_and_junk_are_not_images_whatever_their_name(self):
		for content in (b"", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"<!doctype html><script>x</script>",
		                b"\xef\xbb\xbf<html>", b"RIFF\x10\x00\x00\x00WAVEfmt ", b"\x89PNG", b"GIF8", b"%PDF-1.7",
		                b"   <?xml version='1.0'?><svg/>"):
			self.assertIsNone(ft.sniff_image(content), content)

	def test_active_content_is_known_by_its_last_extension(self):
		for name in ("a.svg", "A.SVG", "x.svgz", "p.html", "p.HTM", "p.xhtml", "p.shtml", "p.xht", "d.xml",
		             "s.xsl", "j.js", "j.mjs", "f.swf", "logo.png.svg", "/files/logo.svg"):
			self.assertTrue(ft.is_active_name(name), name)
		for name in ("a.png", "a.svg.png", "a.pdf", "notes.txt", "noext", "", None, "archive.tar.gz"):
			self.assertFalse(ft.is_active_name(name), name)

	def test_a_site_image_is_an_image_address(self):
		for url in ("/files/logo.png", "/files/hotel%20logo.webp", "/private/files/x.jpg", "/assets/kamra/hero.jpg",
		            "https://images.example.com/hero.webp", "https://cdn.example.com/a.svg"):
			self.assertTrue(ft.safe_image_url(url), url)
		for url in ("javascript:alert(1)", "http://insecure.example/logo.png", "/files/evil.svg", "/files/p.html",
		            "//evil.example/x.png", 'https://x.example/a.png" onerror="alert(1)', "data:image/png;base64,AA",
		            "/app/user", "https://x.example/a b.png", "/files/", "https://"):
			self.assertFalse(ft.safe_image_url(url), url)
