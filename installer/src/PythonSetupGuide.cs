using System;
using System.Drawing;
using System.Windows.Forms;

namespace AIPraat.Setup
{
    public sealed class PythonSetupGuide : LinkLabel
    {
        public PythonSetupGuide()
        {
            Text="运行Powershell命令一键配置 →";Name="ConfigurePython";AccessibleName=Text;
            AutoSize=false;Size=new Size(820,30);Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            LinkColor=Color.FromArgb(0,80,160);ActiveLinkColor=LinkColor;VisitedLinkColor=LinkColor;
            Visible=false;TabStop=true;Cursor=Cursors.Hand;
        }
        public void Refresh(PythonProbe probe,bool allowed,bool running)
        {
            Visible=allowed&&probe!=null&&probe.CanConfigure;Enabled=!running;
            Text=running?"正在运行Powershell配置，请在命令窗口查看进度…":"运行Powershell命令一键配置 →";
        }
    }
}
