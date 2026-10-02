using System;
using System.IO;
using System.Drawing;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Reflection;

namespace AIPraat.Setup
{
    public sealed class WizardForm : Form
    {
        readonly InstallRequest request;
        readonly Func<Stream> payloadFactory;
        readonly Panel[] pages=new Panel[3];
        readonly Label[] steps=new Label[3];
        readonly OutlineButton next=new OutlineButton(), previous=new OutlineButton(), cancel=new OutlineButton(), elevate=new OutlineButton();
        readonly TextBox directory=new TextBox(), python=new TextBox(), llama=new TextBox(), model=new TextBox(), mmproj=new TextBox();
        readonly RadioButton skip=new RadioButton(), configure=new RadioButton();
        readonly Label directoryNote=new Label(), prerequisiteNote=new Label(), progressText=new Label(), completionText=new Label();
        readonly PythonSetupGuide setup=new PythonSetupGuide();
        readonly ProgressBar bar=new ProgressBar();
        readonly Timer pythonTimer=new Timer {Interval=650}, progressTimer=new Timer {Interval=40};
        readonly ToolTip tips=new ToolTip();
        readonly CheckBox desktop=new CheckBox();
        readonly List<Control> fields=new List<Control>();
        readonly AlignmentPathFields alignmentFields=new AlignmentPathFields();
        readonly Panel prerequisiteValidation=new Panel {Dock=DockStyle.Fill};
        readonly RowStyle prerequisiteValidationRow=new RowStyle(SizeType.Absolute,0);
        PythonProbe probe;
        string checkedPython="";
        int step, pythonGeneration;
        bool suppressChecks;
        bool installing, finished, failure, requireElevation, previousLoaded, configuringPython;
        AlignmentPaths originalAlignmentPaths;
        volatile InstallProgress latest;
        public WizardForm(InstallRequest defaults,Func<Stream> payload)
        {
            request=defaults; payloadFactory=payload;
            Text="AIPraat 安装向导"; Name="AIPraatInstaller"; AccessibleName=Text;
            Font=new Font("Microsoft YaHei UI",9.5f);
            BackColor=Color.White; ClientSize=new Size(900,690); MinimumSize=new Size(820,650);
            StartPosition=FormStartPosition.CenterScreen; AutoScaleMode=AutoScaleMode.Dpi;
            MaximizeBox=false;
            var layout=new TableLayoutPanel {Dock=DockStyle.Fill,RowCount=4,ColumnCount=1,Padding=new Padding(28,20,28,14)};
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute,104));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            layout.RowStyles.Add(prerequisiteValidationRow);
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute,62)); Controls.Add(layout);
            var header=new Panel{Dock=DockStyle.Fill};
            var title=LabelAt(header,"AIPraat 安装向导",0,0,820,36); title.Font=new Font(Font.FontFamily,19,FontStyle.Bold);
            for(int i=0;i<3;i++) {
                steps[i]=LabelAt(header,(i+1)+"  "+new[]{"选择安装目录","配置前置软件","安装程序"}[i],i*270,53,262,34);
                steps[i].TextAlign=ContentAlignment.MiddleLeft;
            }
            layout.Controls.Add(header,0,0);
            var content=new Panel{Dock=DockStyle.Fill,AutoScroll=true}; layout.Controls.Add(content,0,1);
            for(int i=0;i<3;i++) { pages[i]=new Panel{Dock=DockStyle.Fill,AutoScroll=true}; content.Controls.Add(pages[i]); }
            layout.Controls.Add(prerequisiteValidation,0,2);
            BuildDirectoryPage(); BuildPrerequisitePage(); BuildProgressPage();
            var footer=new FlowLayoutPanel {Dock=DockStyle.Fill,FlowDirection=FlowDirection.RightToLeft,Padding=new Padding(0,12,0,0)};
            next.Text="下一步"; next.Name="Next"; next.AccessibleName="下一步";
            previous.Text="上一步"; previous.Name="Previous"; cancel.Text="取消"; cancel.Name="Cancel";
            elevate.Text="以管理员权限重试"; elevate.Visible=false; elevate.Width=180;
            foreach(var button in new[]{next,previous,cancel,elevate}) {
                button.Height=38; if(button!=elevate) button.Width=108;
                button.Margin=new Padding(8,0,0,0); footer.Controls.Add(button);
            }
            layout.Controls.Add(footer,0,3);
            next.Click+=(s,e)=>Next(); previous.Click+=(s,e)=>ShowStep(Math.Max(0,step-1));
            cancel.Click+=(s,e)=>Close(); elevate.Click+=(s,e)=>Elevate();
            pythonTimer.Tick+=(s,e)=>{ pythonTimer.Stop(); CheckPython(); };
            progressTimer.Tick+=(s,e)=>ApplyProgress();
            FormClosing+=(s,e)=>{ if(installing||configuringPython) e.Cancel=true; };
            FormClosed+=(s,e)=>{pythonTimer.Dispose();progressTimer.Dispose();tips.Dispose();};
            directory.Text=defaults.InstallDirectory; desktop.Checked=defaults.CreateDesktopShortcut;
            ShowStep(0);
        }
        static Label LabelAt(Control parent,string text,int x,int y,int width,int height)
        {
            var label=new Label {Text=text,Location=new Point(x,y),Size=new Size(width,height),AutoSize=false};
            parent.Controls.Add(label); return label;
        }
        void BuildDirectoryPage()
        {
            var page=pages[0];
            var title=LabelAt(page,"选择 AIPraat 安装位置",0,10,800,32); title.Font=new Font(Font,FontStyle.Bold);
            LabelAt(page,"可直接输入完整路径，也可以浏览选择文件夹。",0,50,800,34);
            directory.Location=new Point(0,100); directory.Size=new Size(690,30); directory.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            directory.Name="InstallDirectory"; directory.AccessibleName="安装目录"; page.Controls.Add(directory);
            var browse=new OutlineButton{Text="浏览…",Name="BrowseInstallDirectory",Location=new Point(708,98),Size=new Size(112,34),Anchor=AnchorStyles.Right|AnchorStyles.Top};
            page.Controls.Add(browse); browse.Click+=(s,e)=>{
                using(var dialog=new FolderBrowserDialog {Description="选择 AIPraat 的安装文件夹",ShowNewFolderButton=true}) {
                    if(Directory.Exists(PathValidation.Clean(directory.Text))) dialog.SelectedPath=PathValidation.Clean(directory.Text);
                    if(dialog.ShowDialog(this)==DialogResult.OK) directory.Text=dialog.SelectedPath;
                }
            };
            directoryNote.Location=new Point(0,148); directoryNote.Size=new Size(810,64); directoryNote.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            page.Controls.Add(directoryNote); directory.TextChanged+=(s,e)=>RefreshNext();
            desktop.Text="创建桌面快捷方式"; desktop.Location=new Point(0,242); desktop.Size=new Size(300,28); page.Controls.Add(desktop);
            LabelAt(page,"默认位置：C:\\AIPraat\n如果该文件夹已经存在，将使用同一个文件夹，保留其中的其他文件。",0,298,810,78);
            LabelAt(page,"本安装包包含 Praat 和 AI 前端程序；Python 环境及模型文件需要另行准备。\n当前 Praat 为 Windows 64 位 x64-v3 版本，处理器需要支持 AVX2 等指令。",0,389,810,60).ForeColor=Color.DimGray;
        }
        void BuildPrerequisitePage()
        {
            var page=pages[1];
            var title=LabelAt(page,"是否现在配置前置软件路径？",0,4,810,32); title.Font=new Font(Font,FontStyle.Bold);
            skip.Text="暂不配置，先安装程序"; skip.Location=new Point(0,44); skip.Size=new Size(285,28);
            configure.Text="现在配置"; configure.Location=new Point(315,44); configure.Size=new Size(240,28);
            skip.Name="SkipPrerequisites"; configure.Name="ConfigurePrerequisites"; skip.Checked=true;
            page.Controls.Add(skip); page.Controls.Add(configure);
            AddFileField(page,python,"Python 环境（必需）","选择环境中的 python.exe",88,"PythonPath","Python 解释器|python.exe|可执行文件|*.exe");
            AddFileField(page,llama,"llama.cpp（可选）","选择 llama-server.exe，可留空",167,"LlamaServerPath","llama-server|llama-server.exe|可执行文件|*.exe");
            AddFileField(page,model,"前端模型（可选）","选择模型 .gguf，可留空",246,"ModelPath","GGUF 模型|*.gguf");
            AddFileField(page,mmproj,"视觉投影（可选）","选择与模型匹配的 mmproj .gguf，可留空",325,"MmprojPath","GGUF 视觉投影|*.gguf");
            fields.AddRange(alignmentFields.Add(page,404,tips));alignmentFields.Changed+=(s,e)=>RefreshNext();
            prerequisiteNote.Location=new Point(0,4); prerequisiteNote.Size=new Size(820,46); prerequisiteNote.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            prerequisiteValidation.Controls.Add(prerequisiteNote);
            setup.Location=new Point(0,52);prerequisiteValidation.Controls.Add(setup);setup.LinkClicked+=(s,e)=>ConfigurePython();
            foreach(var field in new[]{llama,model,mmproj}) field.TextChanged+=(s,e)=>RefreshNext();
            python.TextChanged+=(s,e)=>{
                pythonGeneration++; probe=null; checkedPython=""; pythonTimer.Stop();
                if(configure.Checked && !suppressChecks) pythonTimer.Start();
                RefreshNext();
            };
            configure.CheckedChanged+=(s,e)=>{
                pythonGeneration++; probe=null; checkedPython="";
                foreach(var control in fields) control.Enabled=configure.Checked;
                if(configure.Checked && python.Text!="" && !suppressChecks) pythonTimer.Start();
                else pythonTimer.Stop();
                RefreshNext();
            };
            foreach(var control in fields) control.Enabled=false;
        }
        void AddFileField(Panel page,TextBox input,string label,string hint,int top,string name,string filter)
        {
            fields.AddRange(FilePathField.Add(page,input,label,hint,top,name,filter,tips));
        }
        async void CheckPython()
        {
            if(!configure.Checked||installing||configuringPython||IsDisposed) return;
            string target=PathValidation.Clean(python.Text);
            int generation=++pythonGeneration;
            probe=null; checkedPython=target; RefreshNext();
            PythonProbe result=await Task.Run(()=>PathValidation.ProbePython(target));
            if(IsDisposed||!configure.Checked||generation!=pythonGeneration||PathValidation.Clean(python.Text)!=target) return;
            probe=result; checkedPython=target; RefreshNext();
        }
        async void ConfigurePython()
        {
            if(configuringPython||installing||!configure.Checked||probe==null||!probe.CanConfigure)return;
            string selected=PathValidation.Clean(python.Text);
            configuringPython=true;pythonGeneration++;pythonTimer.Stop();
            foreach(var control in fields)control.Enabled=false;
            skip.Enabled=configure.Enabled=next.Enabled=previous.Enabled=cancel.Enabled=false;
            setup.Refresh(probe,true,true);prerequisiteNote.Text="正在配置所选 Python 环境，请在 PowerShell 窗口查看进度。";
            try {await Task.Run(()=>PythonSetup.Run(selected));}
            catch(Exception e) {MessageBox.Show(this,"无法启动一键配置："+e.Message,"运行环境配置",MessageBoxButtons.OK,MessageBoxIcon.Error);}
            finally {
                configuringPython=false;
                if(!IsDisposed){foreach(var control in fields)control.Enabled=configure.Checked;skip.Enabled=configure.Enabled=previous.Enabled=cancel.Enabled=true;CheckPython();}
            }
        }
        void BuildProgressPage()
        {
            var page=pages[2];
            ReplaceLabel(page,completionText,"准备安装",0,24,810,44);
            completionText.Font=new Font(Font.FontFamily,17,FontStyle.Bold);
            bar.Location=new Point(0,98); bar.Size=new Size(820,26); bar.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            bar.Minimum=0;bar.Maximum=100;bar.Style=ProgressBarStyle.Continuous;bar.Name="InstallationProgress";page.Controls.Add(bar);
            progressText.Location=new Point(0,145);progressText.Size=new Size(820,90);progressText.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;page.Controls.Add(progressText);
        }
        static Label ReplaceLabel(Control parent,Label label,string text,int x,int y,int w,int h)
        {
            label.Text=text;label.Location=new Point(x,y);label.Size=new Size(w,h);parent.Controls.Add(label);return label;
        }
        void LoadPrevious()
        {
            if(previousLoaded) return; previousLoaded=true;
            originalAlignmentPaths=null;
            string root=PathValidation.Clean(directory.Text), settings=Path.Combine(root,"install-settings.json"), config=Path.Combine(root,"ai","ai_config.json");
            try {
                var json=new JavaScriptSerializer();
                if(File.Exists(settings)) {
                    var data=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(settings));
                    if(data.ContainsKey("python_path")) python.Text=Convert.ToString(data["python_path"]);
                }
                if(File.Exists(config)) {
                    var configuration=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(config));
                    var data=Configuration.Object(configuration,"server");
                    object value;
                    if(data.TryGetValue("llama_server",out value)) llama.Text=Convert.ToString(value);
                    if(data.TryGetValue("model_path",out value)) model.Text=Convert.ToString(value);
                    if(data.TryGetValue("mmproj_path",out value)) mmproj.Text=Convert.ToString(value);
                    originalAlignmentPaths=AlignmentPaths.Read(configuration);alignmentFields.Fill(originalAlignmentPaths);
                }
            } catch { /* Existing invalid configuration is reported transactionally during installation. */ }
        }
        void ShowStep(int value)
        {
            step=value;
            prerequisiteValidationRow.Height=step==1?90:0;prerequisiteValidation.Visible=step==1;
            for(int i=0;i<3;i++) {
                pages[i].Visible=i==step; steps[i].ForeColor=i==step?Color.Black:Color.Gray;
                steps[i].Font=new Font(Font,i==step?FontStyle.Bold:FontStyle.Regular);
            }
            if(step==1) LoadPrevious();
            previous.Visible=step>0 && !finished; previous.Enabled=!installing;
            cancel.Visible=!finished; cancel.Enabled=!installing;
            elevate.Visible=step==2 && requireElevation;
            RefreshNext();
        }
        InstallRequest Gather()
        {
            request.InstallDirectory=Path.GetFullPath(PathValidation.Clean(directory.Text)).TrimEnd('\\');
            request.ConfigurePrerequisites=configure.Checked;
            request.CreateDesktopShortcut=desktop.Checked;
            if(configure.Checked) {
                request.PythonPath=PathValidation.Clean(python.Text);
                request.LlamaServerPath=PathValidation.Clean(llama.Text);
                request.ModelPath=PathValidation.Clean(model.Text);
                request.MmprojPath=PathValidation.Clean(mmproj.Text);
                request.AlignmentPaths=alignmentFields.Read();
                request.OriginalAlignmentPaths=originalAlignmentPaths;
            }
            return request;
        }
        void RefreshNext()
        {
            setup.Refresh(probe,configure.Checked,configuringPython);
            if(configuringPython)return;
            next.Text=finished?"完成":step==2?(failure?"重试":"安装中"):"下一步"; next.AccessibleName=next.Text;
            if(step==0) {
                string error=PathValidation.InstallDirectoryError(directory.Text);
                next.Enabled=error==null;
                directoryNote.ForeColor=error==null?Color.DimGray:Color.Firebrick;
                directoryNote.Text=error ?? (Directory.Exists(PathValidation.Clean(directory.Text))?"该文件夹已存在，将直接复用。":"安装时将创建此文件夹。");
                return;
            }
            if(step==1) {
                if(!configure.Checked) {
                    next.Enabled=true; prerequisiteNote.ForeColor=Color.DimGray;
                    prerequisiteNote.Text="可以继续安装。基础 Praat 可直接使用，AI 前置软件路径可稍后配置。"; return;
                }
                var optional=new InstallRequest{LlamaServerPath=llama.Text,ModelPath=model.Text,MmprojPath=mmproj.Text,AlignmentPaths=alignmentFields.Read(),OriginalAlignmentPaths=originalAlignmentPaths};
                string error=PathValidation.OptionalPathsError(optional);
                bool valid=probe!=null&&probe.Valid&&checkedPython==PathValidation.Clean(python.Text)&&error==null;
                next.Enabled=valid; prerequisiteNote.ForeColor=valid?Color.FromArgb(30,110,50):Color.Firebrick;
                prerequisiteNote.Text=error ?? (probe!=null?probe.Message:python.Text==""?"请选择 Python 3.10+ 的 python.exe；需含 Tk、NumPy、Pillow 与云端编排依赖，可用下方一键配置补齐。":"正在检查 Python 环境…");
                return;
            }
            next.Enabled=finished || failure;
        }
        void Next()
        {
            if(!next.Enabled) return;
            if(finished) {Close();return;}
            if(step==0) {previousLoaded=false; ShowStep(1);return;}
            if(step==1 || failure) StartInstallation();
        }
        public void Resume()
        {
            suppressChecks=true; pythonTimer.Stop(); pythonGeneration++;
            directory.Text=request.InstallDirectory;
            python.Text=request.PythonPath; llama.Text=request.LlamaServerPath;
            model.Text=request.ModelPath; mmproj.Text=request.MmprojPath;
            if(request.AlignmentPaths!=null)alignmentFields.Fill(request.AlignmentPaths);
            originalAlignmentPaths=request.OriginalAlignmentPaths;
            desktop.Checked=request.CreateDesktopShortcut; configure.Checked=request.ConfigurePrerequisites;
            previousLoaded=true;
            if(request.ConfigurePrerequisites) {
                checkedPython=PathValidation.Clean(python.Text);
                probe=new PythonProbe(true,"前置环境已在原安装窗口检查。");
            }
            suppressChecks=false;
            ShowStep(2); Shown+=(s,e)=>RunInstallation(request);
        }
        void StartInstallation() { RunInstallation(Gather()); }
        async void RunInstallation(InstallRequest plan)
        {
            failure=finished=requireElevation=false; installing=true; latest=null; bar.Value=0;
            completionText.Text="正在安装 AIPraat";
            progressText.Text="0%  ·  正在准备安装文件…";
            ShowStep(2); progressTimer.Start();
            try {
                await Task.Run(()=>{
                    using(var payload=payloadFactory()) new InstallEngine().Run(plan,payload,x=>latest=x);
                });
                ApplyProgress();bar.Value=100;finished=true;
                completionText.Text="安装已完成";
                progressText.Text="100%  ·  安装位置："+plan.InstallDirectory+"\n请从 AIPraat 桌面或开始菜单快捷方式启动。"+
                    (plan.ConfigurePrerequisites?"":"\nAI 前置软件可稍后重新运行本安装器配置。");
            } catch(Exception e) {
                failure=true;requireElevation=e is UnauthorizedAccessException;
                completionText.Text="安装未完成";
                progressText.Text=e.Message+(requireElevation?"\n此位置需要写入权限。可返回选择其他目录，或以管理员权限重试。":"\n请处理上述问题后重试，或返回修改安装选项。");
            } finally {
                installing=false;progressTimer.Stop();ShowStep(2);
            }
        }
        void ApplyProgress()
        {
            var p=latest;if(p==null)return;bar.Value=p.Percent;progressText.Text=p.Percent+"%  ·  "+p.Message;
        }
        void Elevate()
        {
            string path=Path.Combine(Path.GetTempPath(),"AIPraat-resume-"+Guid.NewGuid().ToString("N")+".json");
            try {
                File.WriteAllText(path,new JavaScriptSerializer().Serialize(request),new System.Text.UTF8Encoding(false));
                Process.Start(new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
                    "--resume "+PathValidation.QuoteArgument(path)){UseShellExecute=true,Verb="runas"});
                Close();
            } catch(System.ComponentModel.Win32Exception) {
                if(File.Exists(path))File.Delete(path);
                progressText.Text="管理员权限未获批准。可返回选择可写入的文件夹。";
            } catch(Exception e) { progressText.Text=e.Message; }
        }
    }
}
