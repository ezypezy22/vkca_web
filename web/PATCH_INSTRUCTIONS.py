"""
PATCH INSTRUCTIONS — add --web flag to vkcontest_analyzer.py
=============================================================

In vkcontest_analyzer.py, find the entry-point block at the very bottom
(the `if __name__ == "__main__":` section) and replace it with the version
below.  The only change is the 10-line block that checks for --web before
the normal Tk startup path.

------- REPLACE the existing entry-point block with this: -------

if __name__ == "__main__":
    # ── --web mode: PyWebView + FastAPI instead of tkinter ───────────────
    if "--web" in sys.argv:
        sys.argv.remove("--web")
        from web.server import launch_webview
        db_path = sys.argv[1] if len(sys.argv) > 1 else None
        launch_webview(db_path=db_path)
        sys.exit(0)

    # ── Normal tkinter mode (unchanged) ──────────────────────────────────
    # High-DPI awareness (Windows) — must run before any Tk window
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    root.withdraw()

    splash = SplashScreen(root)

    def _launch():
        def _show_plugin_splash():
            def _open_app():
                app = App(root)
                app.withdraw()

                def _show():
                    app.attributes("-alpha", 0.0)
                    app.deiconify()
                    app.lift()
                    _fade_in(app, target_alpha=1.0, step=0.08)
                    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
                        app._db_path = sys.argv[1]
                        app._manual_refresh()

                root.after(200, _show)

            PluginSplashScreen(root, on_done_cb=_open_app)

        root.after(0, _show_plugin_splash)

    splash._on_accept_cb = _launch
    root.mainloop()

------- END OF PATCH -------
"""
