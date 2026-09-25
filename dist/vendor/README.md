# Local PDF export assets

These files are loaded from the Afterword origin only when a PDF export is requested. They do not use a CDN or a font service.

- `pdfmake.min.js`: pdfmake 0.2.20 browser build from the official npm package, MIT license in `pdfmake-LICENSE.txt`.
- `report-fonts.js`: unmodified Noto Sans Regular/Bold, Noto Sans Devanagari Regular/Bold, and Noto Sans Symbols 2 Regular font bytes encoded in a virtual file system. Fonts are licensed under SIL OFL 1.1 (`Noto-OFL.txt`). Font cmap coverage is included for explicit fallback instead of missing-glyph boxes.
- `report-assets.json`: pinned upstream URLs, package integrity, and original font SHA-256 digests. Fonts are from noto-fonts commit `ffebf8c1ee449e544955a7e813c54f9b73848eac`.

The embedded fonts cover all four current application languages (English, Spanish, Vietnamese, Hindi), plus common symbols. Unsupported characters are shown as Unicode code points, with a notice in the PDF. Reports never silently drop unsupported text. Input strings are plain text and cannot supply PDF links, scripts, images, or other document-definition instructions.

Source documentation: https://pdfmake.github.io/docs/0.1/getting-started/client-side/ and https://pdfmake.github.io/docs/0.1/fonts/custom-fonts-client-side/vfs/.
