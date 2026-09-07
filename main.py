import webview


def main() -> None:
    """Launch the desktop shell."""
    webview.create_window(
        "Xalling",
        html="""
        <!doctype html>
        <html lang=\"en\">
          <head>
            <meta charset=\"utf-8\">
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
            <title>Xalling</title>
            <style>
              body { align-items: center; background: #10131a; color: #f4f7fb;
                     display: flex; font-family: system-ui, sans-serif; height: 100vh;
                     justify-content: center; margin: 0; }
              main { text-align: center; }
              h1 { font-size: 2.5rem; margin-bottom: .25rem; }
              p { color: #aeb8ca; }
            </style>
          </head>
          <body><main><h1>Xalling</h1><p>pywebview is ready.</p></main></body>
        </html>
        """,
        width=1000,
        height=700,
    )
    webview.start()


if __name__ == "__main__":
    main()
