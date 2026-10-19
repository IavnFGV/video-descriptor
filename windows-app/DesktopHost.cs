using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace VideoDescriptor {
    public class DesktopHost : Form {
        [STAThread]
        public static int Main(string[] args) {
            try {
                string directory = args.Length > 0 ? args[0] : Path.GetDirectoryName(Path.GetDirectoryName(Application.ExecutablePath));
                string root = Path.GetDirectoryName(directory);
                string python = args.Length > 1 ? args[1] : Path.Combine(root, "python", "python.exe");
                if (!File.Exists(python)) python = Path.Combine(root, ".venv-windows", "Scripts", "python.exe");
                if (!File.Exists(python)) throw new Exception("Application Python runtime is missing. Reinstall the preview.");
                Run(python, directory, args.Length > 2 && args[2] == "--smoke");
                return 0;
            } catch (Exception ex) {
                if (args.Length > 2 && args[2] == "--smoke") {
                    File.WriteAllText(Path.Combine(args[0], "runtime", "desktop-smoke-error.txt"), ex.ToString());
                    return 1;
                }
                MessageBox.Show(ex.Message, "Video Descriptor - startup error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
        readonly string python, directory;
        readonly WebView2 web = new WebView2();
        readonly Label status = new Label();
        readonly Button retry = new Button();
        readonly NotifyIcon tray = new NotifyIcon();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        readonly HttpClient http = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        Dictionary<string, object> session;
        EventWaitHandle activate;
        bool busy, monitoring, quitting, initialized;
        string failure;
        readonly bool smoke;
        bool smokeRunning;

        public DesktopHost(string py, string dir, bool test) {
            python = py; directory = dir; smoke = test;
            Text = "Video Descriptor"; Size = new Size(1200, 820); MinimumSize = new Size(760, 560);
            StartPosition = FormStartPosition.CenterScreen;
            Icon = new Icon(Path.Combine(dir, "app.ico"));
            http.Timeout = TimeSpan.FromSeconds(2);
            var bar = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 42 };
            var home = new Button { Text = "Главная", AutoSize = true };
            home.Click += delegate { if (session != null && initialized) web.Source = new Uri((string)session["url"]); };
            retry.Text = "Подключиться снова"; retry.AutoSize = true;
            retry.Click += async delegate { await Connect(); };
            bar.Controls.Add(home); bar.Controls.Add(retry);
            status.Dock = DockStyle.Fill; status.TextAlign = ContentAlignment.MiddleCenter;
            status.Font = new Font("Segoe UI", 11);
            status.Text = "Запуск Video Descriptor…";
            web.Dock = DockStyle.Fill; web.Visible = false;
            Controls.Add(web); Controls.Add(status); Controls.Add(bar);
            tray.Icon = Icon; tray.Text = "Video Descriptor"; tray.Visible = true;
            var menu = new ContextMenuStrip();
            menu.Items.Add("Открыть", null, delegate { Restore(); });
            menu.Items.Add("Завершить приложение", null, async delegate { await Quit(); });
            tray.ContextMenuStrip = menu; tray.DoubleClick += delegate { Restore(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }
            };
            Shown += async delegate { await Connect(); };
            timer.Interval = 2500;
            timer.Tick += async delegate {
                if (activate != null && activate.WaitOne(0)) Restore();
                if (busy || monitoring || session == null) return;
                monitoring = true;
                var checkedSession = session;
                try { await Health(); }
                catch (Exception ex) {
                    if (!busy && Object.ReferenceEquals(session, checkedSession))
                        ShowError("Соединение с backend потеряно. " + ex.Message);
                }
                finally { monitoring = false; }
            };
            timer.Start();
        }

        void Restore() { Show(); WindowState = FormWindowState.Normal; Activate(); }
        void ShowError(string text) {
            web.Visible = false; status.Visible = true; status.Text = text +
                "\n\nЛоги: " + Path.Combine(directory, "runtime", "logs") +
                "\nЗакрытие окна оставляет приложение в трее.";
            retry.Enabled = true;
        }
        public static bool Allowed(string address, string origin) {
            Uri target, expected;
            return Uri.TryCreate(address, UriKind.Absolute, out target) &&
                Uri.TryCreate(origin, UriKind.Absolute, out expected) &&
                target.Scheme == "http" && target.Host == "127.0.0.1" &&
                target.Port == expected.Port && target.UserInfo == "";
        }
        async Task Health() {
            var expected = session;
            string body = await http.GetStringAsync((string)expected["url"] + "/health");
            var info = json.Deserialize<Dictionary<string, object>>(body);
            foreach (string key in new [] { "instance", "workspace", "installation" })
                if (!info.ContainsKey(key) || !Object.Equals(info[key], expected[key]))
                    throw new Exception("На порту другой экземпляр приложения.");
            if ((string)info["app"] != "video-descriptor-windows" || Convert.ToInt32(info["desktop_protocol"]) != 1)
                throw new Exception("Неизвестный backend.");
        }
        async Task Connect() {
            if (busy) return;
            busy = true; retry.Enabled = false;
            web.Visible = false; status.Visible = true; status.Text = "Подключение к локальному backend…";
            try {
                string output = await Task.Run(() => {
                    var start = new ProcessStartInfo(python, "-X utf8 \"" + Path.Combine(directory, "desktop.py") + "\"");
                    start.UseShellExecute = false; start.CreateNoWindow = true;
                    start.RedirectStandardOutput = true; start.RedirectStandardError = true;
                    start.StandardOutputEncoding = Encoding.UTF8; start.StandardErrorEncoding = Encoding.UTF8;
                    start.WorkingDirectory = Path.GetDirectoryName(directory);
                    using (var process = Process.Start(start)) {
                        string stdout = process.StandardOutput.ReadToEnd();
                        string stderr = process.StandardError.ReadToEnd();
                        process.WaitForExit();
                        if (process.ExitCode != 0) throw new Exception(stderr);
                        return stdout;
                    }
                });
                session = json.Deserialize<Dictionary<string, object>>(output);
                await Health();
                if (!initialized) {
                    string fixedRuntime = Path.Combine(directory, "webview2-runtime");
                    if (!File.Exists(Path.Combine(fixedRuntime, "msedgewebview2.exe"))) fixedRuntime = null;
                    var env = await CoreWebView2Environment.CreateAsync(fixedRuntime, Path.Combine(directory, "runtime", "webview"));
                    await web.EnsureCoreWebView2Async(env);
                    var core = web.CoreWebView2;
                    core.Settings.AreHostObjectsAllowed = false;
                    core.Settings.IsWebMessageEnabled = false;
                    core.Settings.AreDevToolsEnabled = false;
                    core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                    core.Settings.AreDefaultContextMenusEnabled = false;
                    core.PermissionRequested += delegate(object s, CoreWebView2PermissionRequestedEventArgs e) { e.State = CoreWebView2PermissionState.Deny; };
                    core.ProcessFailed += delegate { ShowError("Процесс WebView2 завершился. Закройте приложение через трей и откройте снова. Backend продолжает работу."); };
                    core.NavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs e) { e.Cancel = !Allowed(e.Uri, (string)session["url"]); };
                    core.FrameNavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs e) { e.Cancel = !Allowed(e.Uri, (string)session["url"]); };
                    core.NewWindowRequested += delegate(object s, CoreWebView2NewWindowRequestedEventArgs e) {
                        e.Handled = true;
                        if (Allowed(e.Uri, (string)session["url"])) core.Navigate(e.Uri);
                    };
                    core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
                    core.WebResourceRequested += delegate(object s, CoreWebView2WebResourceRequestedEventArgs e) {
                        if (!Allowed(e.Request.Uri, (string)session["url"]))
                            e.Response = env.CreateWebResourceResponse(new MemoryStream(), 403, "Blocked", "Content-Type: text/plain");
                    };
                    core.NavigationCompleted += async delegate(object s, CoreWebView2NavigationCompletedEventArgs e) {
                        if (!e.IsSuccess) { ShowError("Не удалось загрузить интерфейс: " + e.WebErrorStatus); return; }
                        if (smoke && !smokeRunning) {
                            smokeRunning = true;
                            try {
                                string content = await core.ExecuteScriptAsync("document.body.innerText");
                                if (content.Length < 80) throw new Exception("UI document is empty");
                                string setup = await core.ExecuteScriptAsync("['setup-wizard','download-consent','probe-model','gemini-form','setup-finish'].every(id=>!!document.getElementById(id)) && typeof document.getElementById('setup-open').onclick === 'function'");
                                if (setup != "true") throw new Exception("AI setup DOM or handlers missing");
                                string job = Path.Combine((string)session["workspace"], "output", "jobs", "desktop-smoke", "job.json");
                                Directory.CreateDirectory(Path.GetDirectoryName(job));
                                File.WriteAllText(job, "{\"status\":\"running\"}");
                                try {
                                    var stop = new HttpRequestMessage(HttpMethod.Post, (string)session["url"] + "/api/native/stop");
                                    stop.Headers.Add("X-App-Instance", (string)session["instance"]);
                                    stop.Content = new ByteArrayContent(new byte[0]);
                                    if ((await http.SendAsync(stop)).StatusCode != HttpStatusCode.Conflict)
                                        throw new Exception("Active queue was not protected");
                                    Close();
                                    if (Visible || IsDisposed) throw new Exception("Close did not hide to tray");
                                    await Health();
                                    var repeat = new ProcessStartInfo(Application.ExecutablePath,
                                        "\"" + directory + "\" \"" + python + "\"") { UseShellExecute = false };
                                    using (var second = Process.Start(repeat)) {
                                        bool exited = await Task.Run(() => second.WaitForExit(10000));
                                        if (!exited || second.ExitCode != 0) throw new Exception("Second window was not suppressed");
                                    }
                                    await Task.Delay(3000);
                                    if (!Visible) throw new Exception("Repeated launch did not restore window");
                                } finally { File.Delete(job); }
                                var shutdown = new HttpRequestMessage(HttpMethod.Post, (string)session["url"] + "/api/native/stop");
                                shutdown.Headers.Add("X-App-Instance", (string)session["instance"]);
                                shutdown.Content = new ByteArrayContent(new byte[0]);
                                (await http.SendAsync(shutdown)).EnsureSuccessStatusCode();
                                await Task.Delay(6000);
                                if (!status.Visible || !status.Text.Contains("backend"))
                                    throw new Exception("Backend loss did not show an error screen");
                                await Connect();
                                if (!web.Visible || status.Visible) throw new Exception("Retry did not restore WebView");
                                await Health();
                            } catch (Exception ex) { failure = ex.ToString(); }
                            finally { quitting = true; Close(); }
                        }
                    };
                    initialized = true;
                }
                web.Visible = true; status.Visible = false;
                web.CoreWebView2.Navigate((string)session["url"]);
            } catch (Exception ex) {
                ShowError(ex.Message + "\nДля окна требуется установленный Microsoft Edge WebView2 Runtime.");
                if (smoke) { failure = ex.ToString(); quitting = true; Close(); }
            } finally { busy = false; retry.Enabled = true; }
        }
        async Task Quit() {
            if (busy) return;
            busy = true;
            try {
                if (session != null) {
                    await Health();
                    var request = new HttpRequestMessage(HttpMethod.Post, (string)session["url"] + "/api/native/stop");
                    request.Headers.Add("X-App-Instance", (string)session["instance"]);
                    request.Content = new ByteArrayContent(new byte[0]);
                    var response = await http.SendAsync(request);
                    if (response.StatusCode == HttpStatusCode.Conflict) {
                        MessageBox.Show("Обработка ещё выполняется. Дождитесь завершения. Окно можно закрыть в трей.", Text);
                        return;
                    }
                    response.EnsureSuccessStatusCode();
                }
                quitting = true; Close();
            } catch (Exception ex) {
                // Closing only the shell is always safe: no process termination, even after a crash.
                if (MessageBox.Show("Backend недоступен: " + ex.Message + "\nЗакрыть только окно и трей? Обработка не будет остановлена.", Text,
                    MessageBoxButtons.YesNo) == DialogResult.Yes) { quitting = true; Close(); }
            } finally { busy = false; }
        }
        protected override void Dispose(bool disposing) {
            if (disposing) { timer.Dispose(); tray.Dispose(); http.Dispose(); web.Dispose(); }
            base.Dispose(disposing);
        }
        public static void Verify() {
            string root = "http://127.0.0.1:8780";
            if (!Allowed(root + "/create", root) || Allowed("https://example.org", root) ||
                Allowed("http://127.0.0.1:8000", root) || Allowed("file:///C:/Windows", root) ||
                Allowed("http://127.0.0.1.evil.org:8780", root) || Allowed("http://user@127.0.0.1:8780", root))
                throw new Exception("Navigation policy failed");
        }
        public static void Run(string python, string directory) { Run(python, directory, false); }
        public static void Run(string python, string directory, bool smoke) {
            Application.EnableVisualStyles();
            string key;
            using (var hash = SHA256.Create()) key = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(directory.ToLowerInvariant()))).Replace("-", "");
            using (var mutex = new Mutex(false, "Local\\VideoDescriptor-" + key))
            using (var signal = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\VideoDescriptorShow-" + key)) {
                bool owned;
                try { owned = mutex.WaitOne(0); } catch (AbandonedMutexException) { owned = true; }
                if (!owned) { signal.Set(); return; }
                try {
                    using (var window = new DesktopHost(python, directory, smoke)) {
                        window.activate = signal;
                        Application.Run(window);
                        if (window.failure != null) throw new Exception(window.failure);
                    }
                } finally { mutex.ReleaseMutex(); }
            }
        }
    }
}
