import {test,expect,type Page} from '@playwright/test';

async function archive(page:Page,id:string){
  await page.locator(`[data-session-id="${id}"]`).click({button:'right'});
  await page.getByRole('menuitem',{name:'归档会话',exact:true}).click();
  await expect(page.locator(`[data-session-id="${id}"]`)).toHaveCount(0);
}
async function archives(page:Page){
  await page.getByRole('button',{name:'打开设置',exact:true}).click();
  await page.getByRole('button',{name:'已归档会话',exact:true}).click();
  await expect(page.getByRole('heading',{name:'已归档的聊天',exact:true})).toBeVisible();
}

test('archived entry lives in settings; Codex rows show dates and restore without leaving settings',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await archive(page,'demo-1');
  await expect(page.getByRole('button',{name:'查看已归档会话',exact:true})).toHaveCount(0);
  await archives(page);
  const row=page.locator('[data-archived-session-id="demo-1"]');
  await expect(row.getByRole('button',{name:'查看已归档会话 新的分析',exact:true})).toBeVisible();
  await expect(row.locator('time')).toHaveAttribute('datetime',/.+/);
  await expect(page.locator('.archived-group-name')).toContainText('无项目');
  await expect(page.getByRole('button',{name:'保存设置',exact:true})).toHaveCount(0);
  const action=row.getByRole('button',{name:'取消归档 新的分析',exact:true});
  const titleRect=(await row.locator('.archived-session-details').boundingBox())!;
  const actionRect=(await action.boundingBox())!;
  expect(actionRect.x-titleRect.x-titleRect.width).toBeGreaterThanOrEqual(15);
  await action.click();
  await expect(page.getByText('暂无已归档会话',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'已归档的聊天',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'返回聊天',exact:true}).click();
  await expect(page.locator('[data-session-id="demo-1"]')).toBeVisible();
});

test('archive search and source/project filters reuse host results; row delete requires confirmation',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await archive(page,'demo-1');await archive(page,'legacy:fixture');await archives(page);
  await expect(page.getByRole('button',{name:'全部删除',exact:true})).toBeVisible();
  const search=page.getByRole('textbox',{name:'搜索已归档的聊天',exact:true});
  await search.fill('这是一条只读旧记录');await expect(page.locator('.archived-session-row')).toHaveCount(1);
  await expect(page.locator('[data-archived-session-id="legacy:fixture"]')).toBeVisible();
  expect(await search.evaluate(el=>getComputedStyle(el).outlineStyle)).toBe('none');
  await search.fill('');await expect(page.locator('.archived-session-row')).toHaveCount(2);
  await page.getByRole('button',{name:'聊天分类',exact:true}).click();await page.getByRole('menuitemradio',{name:'桌面聊天',exact:true}).click();
  await expect(page.locator('.archived-session-row')).toHaveCount(1);
  const remove=page.getByRole('button',{name:'删除已归档会话 新的分析',exact:true});await remove.click();
  const dialog=page.getByRole('dialog',{name:'删除已归档会话',exact:true});await expect(dialog).toBeVisible();
  await dialog.getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.archived-session-row')).toHaveCount(1);
  await remove.click();await page.getByRole('button',{name:'确认删除归档会话',exact:true}).click();await expect(page.locator('.archived-session-row')).toHaveCount(0);
  await page.getByRole('button',{name:'聊天分类',exact:true}).click();await page.getByRole('menuitemradio',{name:'全部聊天',exact:true}).click();
  await expect(page.locator('[data-archived-session-id="legacy:fixture"]')).toBeVisible();
});

test('archived sections keep original grouping; group and global deletion retain active chats',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await page.getByRole('button',{name:'新建分区',exact:true}).click();await page.getByLabel('分区名称',{exact:true}).fill('声学研究');await page.getByRole('button',{name:'保存分区',exact:true}).click();
  await page.getByRole('button',{name:'会话操作 新的分析',exact:true}).click();await page.getByRole('menuitem',{name:'分区',exact:true}).click();await page.getByRole('menuitem',{name:'声学研究',exact:true}).click();
  await archive(page,'demo-1');await archive(page,'legacy:fixture');await archives(page);
  await expect(page.locator('.archived-group-name')).toContainText(['声学研究','无项目']);
  await page.screenshot({path:process.env.PI_SCRATCH_DIR+'/archived-settings-desktop.png'});
  await page.getByRole('button',{name:'项目分类',exact:true}).click();await page.getByRole('menuitemradio',{name:'声学研究',exact:true}).click();
  await expect(page.locator('.archived-session-row')).toHaveCount(1);
  await page.getByRole('button',{name:'归档分组操作 声学研究',exact:true}).click();await page.getByRole('menuitem',{name:'删除分组中的聊天',exact:true}).click();
  await page.getByRole('button',{name:'确认删除归档会话',exact:true}).click();await expect(page.locator('.archived-session-row')).toHaveCount(0);
  await page.getByRole('button',{name:'项目分类',exact:true}).click();await page.getByRole('menuitemradio',{name:'所有项目',exact:true}).click();
  await page.getByRole('button',{name:'全部删除',exact:true}).click();await expect(page.getByRole('dialog',{name:'删除全部已归档会话',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'确认删除归档会话',exact:true}).click();await expect(page.getByText('暂无已归档会话',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'返回聊天',exact:true}).click();await expect(page.locator('[data-session-id="demo-history"]')).toBeVisible();await expect(page.locator('.session-row')).toHaveCount(2);
});

test('opening archived history respects unsaved settings and restores legacy history as read-only',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await archive(page,'legacy:fixture');await archives(page);
  await page.getByRole('button',{name:'模型',exact:true}).click();await page.getByRole('textbox',{name:'API Key',exact:true}).fill('ephemeral-archive-test');
  await page.getByRole('button',{name:'已归档会话',exact:true}).click();
  await page.getByRole('button',{name:'查看已归档会话 演示旧记录（只读）',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'未保存的设置',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'继续编辑',exact:true}).click();
  await expect(page.getByRole('heading',{name:'已归档的聊天',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'查看已归档会话 演示旧记录（只读）',exact:true}).click();
  await page.getByRole('button',{name:'丢弃并返回',exact:true}).click();
  await expect(page.locator('.chat-header h1')).toContainText('演示旧记录（只读）');
  await expect(page.locator('.archived-conversation')).toContainText('此会话已归档');
  await expect(page.getByRole('textbox',{name:'消息输入',exact:true})).toHaveCount(0);
  await archives(page);await page.getByRole('button',{name:'取消归档 演示旧记录（只读）',exact:true}).click();
  await page.getByRole('button',{name:'返回聊天',exact:true}).click();
  await expect(page.locator('[data-session-id="legacy:fixture"]')).toBeVisible();
  await expect(page.getByRole('textbox',{name:'消息输入',exact:true})).toHaveCount(0);
});

test('archive settings rows remain aligned in a narrow viewport',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();await archive(page,'legacy:fixture');await archives(page);
  await page.setViewportSize({width:650,height:600});
  const row=page.locator('[data-archived-session-id="legacy:fixture"]');
  await expect(row).toBeVisible();
  expect(await page.locator('.settings-main').evaluate(el=>el.scrollWidth-el.clientWidth)).toBeLessThanOrEqual(1);
  const rect=(await row.boundingBox())!,action=(await row.getByRole('button',{name:/取消归档/}).boundingBox())!;
  expect(action.x+action.width).toBeLessThanOrEqual(rect.x+rect.width);expect(action.y+action.height).toBeLessThanOrEqual(rect.y+rect.height);
  const groupRect=(await page.locator('.archived-group-list').boundingBox())!;expect(groupRect.x+groupRect.width-action.x-action.width).toBeGreaterThan(8);
  await page.screenshot({path:process.env.PI_SCRATCH_DIR+'/archived-settings-narrow.png'});
});
