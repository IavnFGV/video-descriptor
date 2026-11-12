// Focused runtime checks for the WinForms/WebView2 desktop shell.
// Compiled and executed by tests/test_desktop_shell.py; never packaged or shipped.
// The window is exercised with a deliberately missing Python runtime, so the
// native recovery path is verified without a backend, WebView2 content or models.
using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;

namespace VideoDescriptor {
    static class DesktopShellHarness {
        // Non-ASCII literals stay escaped: the source is read as UTF-8 by any compiler.
        const string Home = "\u0413\u043b\u0430\u0432\u043d\u0430\u044f";
        const string Retry = "\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f \u0441\u043d\u043e\u0432\u0430";
        const string Open = "\u041e\u0442\u043a\u0440\u044b\u0442\u044c";
        const string Quit = "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435";

        static void Require(bool condition, string message) {
            if (!condition) throw new Exception(message);
        }

        static object Member(object instance, string name) {
            FieldInfo field = typeof(DesktopHost).GetField(name, BindingFlags.NonPublic | BindingFlags.Instance);
            Require(field != null, "Missing host member: " + name);
            return field.GetValue(instance);
        }

        static T Find<T>(Control root, Func<T, bool> match) where T : Control {
            foreach (Control child in root.Controls) {
                T found = child as T;
                if (found != null && match(found)) return found;
                T nested = Find(child, match);
                if (nested != null) return nested;
            }
            return null;
        }

        static void Pump(int milliseconds) {
            DateTime until = DateTime.UtcNow.AddMilliseconds(milliseconds);
            while (DateTime.UtcNow < until) { Application.DoEvents(); Thread.Sleep(20); }
        }

        [STAThread]
        static int Main(string[] args) {
            try {
                string directory = args[0];
                DesktopHost.Verify(); // loopback navigation policy is unchanged
                using (var form = new DesktopHost(Path.Combine(directory, "missing-python-runtime.exe"),
                                                  directory, false, 0)) {
                    WebView2 web = Find<WebView2>(form, delegate { return true; });
                    Require(web != null, "WebView2 is missing");
                    Require(web.Dock == DockStyle.Fill, "WebView2 is not docked to the client area");
                    Require(form.Controls.Count == 2, "Unexpected native controls in the window");
                    Require(Find<Button>(form, delegate(Button b) { return b.Text == Home; }) == null,
                        "Duplicate navigation button is still present");
                    Button retry = Find<Button>(form, delegate(Button b) { return b.Text == Retry; });
                    Require(retry != null, "Native retry button is missing");
                    Require(retry.Parent != form, "Retry button must stay inside the fallback screen");
                    Control fallback = (Control)Member(form, "fallback");
                    Require(!fallback.Visible, "Fallback screen is visible before a connection attempt");
                    NotifyIcon tray = (NotifyIcon)Member(form, "tray");
                    Require(tray.Visible && tray.ContextMenuStrip != null, "Tray integration is missing");
                    bool open = false, quit = false;
                    foreach (ToolStripItem item in tray.ContextMenuStrip.Items) {
                        if (item.Text == Open) open = true;
                        if (item.Text == Quit) quit = true;
                    }
                    Require(open && quit, "Tray menu commands changed");

                    // Normal startup: the failed backend opens the native fallback screen.
                    form.Show();
                    Pump(4000);
                    Require(fallback.Visible, "Connection failure did not show the native fallback");
                    Require(!web.Visible, "WebView stays visible after a failed connection");
                    Require(retry.Visible && retry.Enabled, "Native retry is not available after a failure");
                    Label status = Find<Label>(form, delegate { return true; });
                    Require(status != null && status.Text.Length > 0, "Failure screen has no message");

                    // The retry must work without WebView2 content and without a backend.
                    retry.PerformClick();
                    Pump(4000);
                    Require(fallback.Visible && retry.Enabled, "Retry lost the native recovery screen");
                    Require(!web.Visible, "Retry used a WebView that never connected");

                    // Connected layout: the web interface owns the whole client area.
                    fallback.Visible = false;
                    web.Visible = true;
                    form.PerformLayout();
                    Pump(300);
                    Rectangle client = form.ClientRectangle;
                    Require(web.Bounds.X == 0 && web.Bounds.Y == 0, "WebView2 does not start at the client origin");
                    Require(Math.Abs(web.Bounds.Width - client.Width) <= 2 &&
                            Math.Abs(web.Bounds.Height - client.Height) <= 2,
                        "WebView2 does not fill the client area");
                    Require(form.FormBorderStyle != FormBorderStyle.None, "Standard window frame was removed");

                    // Closing the window hides it into the tray instead of exiting.
                    form.Close();
                    Require(!form.Visible && !form.IsDisposed, "Close did not hide the window into the tray");

                    // Quitting the application disposes the window instead of hiding it.
                    MethodInfo quitCommand = typeof(DesktopHost).GetMethod("Quit",
                        BindingFlags.NonPublic | BindingFlags.Instance);
                    Require(quitCommand != null, "Quit command is missing");
                    Task stopped = (Task)quitCommand.Invoke(form, null);
                    stopped.Wait(15000);
                    Pump(500);
                    Require(form.IsDisposed, "Application exit did not dispose the window");
                }
                Console.WriteLine("desktop shell harness passed");
                return 0;
            } catch (Exception ex) {
                Console.Error.WriteLine(ex.ToString());
                return 1;
            }
        }
    }
}
