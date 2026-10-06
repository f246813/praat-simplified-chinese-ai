import {test,expect} from '@playwright/test';

async function section(page:any,name:string){await page.getByRole('button',{name:'新建分区',exact:true}).click();await page.getByRole('textbox',{name:'分区名称',exact:true}).fill(name);await page.getByRole('button',{name:'保存分区',exact:true}).click();}

test('Codex section menus: create, edit, membership, new chat and remove without deleting history',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await expect(page.getByRole('button',{name:'新建分区',exact:true})).toBeVisible();
  await section(page,'声学研究');
  await page.getByRole('button',{name:'会话操作 新的分析',exact:true}).click();
  await page.getByRole('menuitem',{name:'分区',exact:true}).click();
  await page.getByRole('menuitem',{name:'声学研究',exact:true}).click();
  const group=page.locator('[data-history-section]').filter({has:page.getByRole('button',{name:'折叠分区 声学研究',exact:true})});
  await expect(group.locator('[data-session-id="demo-1"]')).toBeVisible();
  await page.getByRole('button',{name:'分区操作 声学研究',exact:true}).click();await page.getByRole('menuitem',{name:'编辑分区',exact:true}).click();
  await page.getByRole('textbox',{name:'分区名称',exact:true}).fill('共振峰研究');await page.getByRole('button',{name:'保存分区',exact:true}).click();
  await expect(page.getByRole('button',{name:'折叠分区 共振峰研究',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'分区操作 共振峰研究',exact:true}).click();await page.getByRole('menuitem',{name:'新建会话',exact:true}).click();
  await expect(page.locator('.session-row')).toHaveCount(5);
  await expect(page.locator('[data-history-section]').filter({has:page.getByRole('button',{name:'折叠分区 共振峰研究',exact:true})}).locator('.session-row')).toHaveCount(2);
  await page.getByRole('button',{name:'分区操作 共振峰研究',exact:true}).click();await page.getByRole('menuitem',{name:'移除分区',exact:true}).click();
  await page.getByRole('button',{name:'确认移除分区',exact:true}).click();
  await expect(page.getByRole('button',{name:'分区操作 共振峰研究',exact:true})).toHaveCount(0);await expect(page.locator('.session-row')).toHaveCount(5);
});

test('right-click menu forks an independent legacy snapshot; archives restore from settings',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await page.locator('[data-session-id="legacy:fixture"]').click({button:'right'});
  await page.getByRole('menuitem',{name:'分叉会话',exact:true}).click();
  await expect(page.locator('.session-row')).toHaveCount(5);await expect(page.locator('.chat-header h1')).toContainText('分叉');
  await expect(page.locator('.transcript')).toContainText('这是一条只读旧记录');await expect(page.getByRole('textbox',{name:'消息输入'})).toBeEditable();
  await page.locator('[data-session-id="demo-1"]').click({button:'right'});await page.getByRole('menuitem',{name:'归档会话',exact:true}).click();
  await expect(page.locator('[data-session-id="demo-1"]')).toHaveCount(0);
  await page.getByRole('button',{name:'打开设置',exact:true}).click();await page.getByRole('button',{name:'已归档会话',exact:true}).click();
  await expect(page.locator('[data-archived-session-id="demo-1"]')).toBeVisible();
  await page.getByRole('button',{name:'取消归档 新的分析',exact:true}).click();
  await page.getByRole('button',{name:'返回聊天',exact:true}).click();await expect(page.locator('[data-session-id="demo-1"]')).toBeVisible();
});


test('section keyboard picker, cross-section drag, ordered insertion and bulk archive restore',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await section(page,'语音研究');await section(page,'待处理');
  const group=(name:string)=>page.locator('[data-history-section]').filter({has:page.getByRole('button',{name:`折叠分区 ${name}`,exact:true})});
  await page.getByRole('button',{name:'会话操作 新的分析',exact:true}).click();
  await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('menuitem',{name:'返回会话菜单',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowLeft');await expect(page.getByRole('menuitem',{name:'分叉会话',exact:true})).toBeVisible();
  await page.getByRole('menuitem',{name:'分区',exact:true}).click();await page.getByRole('menuitem',{name:'语音研究',exact:true}).click();
  await expect(group('语音研究').locator('.session-row')).toHaveCount(1);
  await page.locator('[data-session-id="legacy:fixture"]').dragTo(page.getByRole('button',{name:'折叠分区 语音研究',exact:true}));
  await expect(group('语音研究').locator('.session-row')).toHaveCount(2);
  await page.locator('[data-session-id="demo-history"]').dragTo(page.getByRole('button',{name:'折叠分区 语音研究',exact:true}));
  await expect(group('语音研究').locator('.session-row')).toHaveCount(3);
  await page.locator('[data-session-id="demo-history"]').dragTo(page.locator('[data-session-id="demo-1"]'));
  await expect.poll(()=>group('语音研究').locator('.session-row').evaluateAll(rows=>rows.map(row=>row.getAttribute('data-session-id')))).toEqual(['demo-history','demo-1','legacy:fixture']);
  await page.locator('[data-session-id="demo-1"]').dragTo(page.getByRole('button',{name:'折叠分区 待处理',exact:true}));
  await expect(group('待处理').locator('.session-row')).toHaveCount(1);
  await page.getByRole('button',{name:'分区操作 语音研究',exact:true}).click();await page.getByRole('menuitem',{name:'归档分区',exact:true}).click();
  await page.getByRole('button',{name:'确认归档分区',exact:true}).click();await expect(page.locator('.session-row')).toHaveCount(2);
  await page.getByRole('button',{name:'打开设置',exact:true}).click();await page.getByRole('button',{name:'已归档会话',exact:true}).click();await expect(page.locator('.archived-session-row')).toHaveCount(2);
  await page.locator('[data-archived-session-id="demo-history"] .archived-session-title').click();await expect(page.locator('.archived-conversation')).toContainText('此会话已归档');await expect(page.getByRole('textbox',{name:'消息输入'})).toHaveCount(0);
  await page.getByRole('button',{name:'分区操作 语音研究',exact:true}).click();await page.getByRole('menuitem',{name:'恢复分区会话',exact:true}).click();await page.getByRole('button',{name:'确认恢复分区',exact:true}).click();
  await expect(page.locator('.session-row')).toHaveCount(4);await expect(page.getByRole('textbox',{name:'消息输入'})).toBeEditable();
  await page.getByRole('button',{name:'折叠分区 语音研究',exact:true}).click();await expect(page.locator('.session-row')).toHaveCount(2);await page.getByRole('button',{name:'展开分区 语音研究',exact:true}).click();await expect(page.locator('.session-row')).toHaveCount(4);
  await page.getByRole('button',{name:'分区操作 语音研究',exact:true}).click();
  await page.screenshot({path:process.env.PI_SCRATCH_DIR+'/codex-section-menu.png'});
});
