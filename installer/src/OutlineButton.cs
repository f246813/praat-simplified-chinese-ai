using System;
using System.Drawing;
using System.Windows.Forms;

namespace AIPraat.Setup
{
    public sealed class OutlineButton : Button
    {
        public Color OutlineColor { get { return Enabled?Color.Black:Color.FromArgb(170,170,170); } }
        public OutlineButton()
        {
            SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);
            FlatStyle=FlatStyle.Flat; BackColor=Color.White; Cursor=Cursors.Hand;
            AccessibleRole=AccessibleRole.PushButton;
        }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
        protected override void OnPaint(PaintEventArgs e)
        {
            Color color=OutlineColor;
            e.Graphics.Clear(Enabled && ClientRectangle.Contains(PointToClient(MousePosition))?Color.FromArgb(244,244,244):Color.White);
            using(var pen=new Pen(color,1)) e.Graphics.DrawRectangle(pen,0,0,Width-1,Height-1);
            TextRenderer.DrawText(e.Graphics,Text,Font,ClientRectangle,color,TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter);
            if(Focused&&Enabled) ControlPaint.DrawFocusRectangle(e.Graphics,new Rectangle(4,4,Width-8,Height-8));
        }
    }
}
