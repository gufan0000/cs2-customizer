# 贡献者许可协议（CLA）

> **中文版为准。** 下方 English version 为方便阅读提供的译文，
> 如两者有歧义，以中文版为准。
>
> **提交 Pull Request 之前请读完这一页。** 它决定了你的代码此后可以被怎么使用——
> 包括**被用在本项目维护者的闭源商业产品里**。这一点写在最前面，不藏在条款中间。

---

## 零、三十秒版本

- 你**保留**自己贡献的著作权，不转让。
- 你授予维护者一份**永久、不可撤销、可再许可**的许可，允许他以**任何许可证**
  （包括闭源商业许可）使用、修改、分发你的贡献。
- 这就意味着：**你的代码可能出现在一个收费的闭源软件里，你不会因此获得报酬。**
- 你确认这些代码是你写的、或你有权提交。
- 本项目本身仍然是 GPL-3.0，你的贡献也会以 GPL-3.0 公开发布。

不接受这些条件是完全合理的选择。你仍然可以开 issue、报缺陷、写文档反馈、
fork 本项目自己维护——这些都不需要签 CLA。

---

## 一、为什么是 CLA 而不是 DCO

本项目由单一作者开发，同时存在一个闭源商业版本（本项目是它的功能子集）。
两者共用同一份代码基。

如果只用 DCO（贡献者仅声明"这代码我有权提交"，不作许可授权），
那么任何被合并的外部贡献都只以 GPL-3.0 授权给项目——维护者**无法**再把它放进闭源版本。
一旦发生，代码基就永久分叉：闭源版必须绕开所有外部贡献，或者整体转为 GPL。

CLA 是把这件事**提前讲清楚**，而不是等你的 PR 合并之后才发现自己的代码进了商业产品。
它对贡献者的代价是真实的，本文档不打算把它说得很轻。

---

## 二、定义

- **「本项目」**：CS2 Customizer，仓库位于 <https://github.com/gufan0000/cs2-customizer>。
- **「维护者」**：本项目的著作权人 孤帆 (gufan)，及其书面指定的继受人。
- **「你」**：接受本协议的自然人；若你代表法人签署，见第七节。
- **「贡献」**：你有意提交给本项目的任何原创作品，包括但不限于源代码、文档、
  测试、判据、配置、素材与注释；提交方式包括 Pull Request、issue 附带的代码块、
  补丁邮件等任何形式。**不包括**你明确标注为「非贡献 / Not a Contribution」的内容。

---

## 三、著作权许可

你**保留**你的贡献的全部著作权。

同时，你就你的贡献授予维护者一份**永久的、全球范围的、非独占的、免费的、
免版税的、不可撤销的**许可，允许维护者：

1. 复制、修改、演绎、公开展示、公开表演你的贡献；
2. 以任何形式分发你的贡献及其演绎作品；
3. **在上述权利范围内进行再许可（sublicense），且不限定再许可所采用的许可证**——
   包括但不限于 GPL-3.0、其他开源许可证、以及**专有的闭源商业许可证**。

第 3 项是本协议的核心，也是它与 DCO 的唯一实质区别。请确认你接受它。

**维护者的义务**：本项目公开发布的版本将以 GPL-3.0-or-later 发布，
你的贡献在其中同样以 GPL-3.0-or-later 提供给所有人。
维护者不会以任何方式限制你自己使用、发布、再许可你自己那份贡献的权利。

---

## 四、专利许可

你就你的贡献授予维护者及本项目的所有使用者一份**永久的、全球范围的、非独占的、
免费的、免版税的、不可撤销的**专利许可，用于制造、使用、许诺销售、销售、进口
及以其他方式转让你的贡献及包含你的贡献的作品。

该许可仅覆盖你所拥有或可授权的、且**必然会被你的贡献本身、
或被你的贡献与其提交时所针对的本项目版本的结合所侵害**的那些专利权利要求。

**防御性终止**：若有任何主体针对本项目或其中包含你的贡献的部分提起专利诉讼
（含交叉请求或反诉），主张其构成直接或间接专利侵权，
则本节授予该主体的专利许可自诉讼提起之日起终止。

---

## 五、你的声明

你声明并保证：

1. **每一份贡献都是你的原创作品**，或你已获得足以作出本协议各项授权的权利；
2. 你的贡献**不含**你无权授权的第三方代码、素材或文档。
   若确实包含第三方内容，你已在提交中**逐处明确标注**其来源与许可证，
   且该许可证与本项目的分发方式兼容；
3. 若你受雇于人、或与他人签有可能影响你贡献著作权归属的协议
   （雇佣合同、职务发明条款、竞业或保密约定等），
   你已取得雇主/相对方的许可，或该等协议已作相应豁免；
4. 你理解并同意：你的贡献连同你的署名、邮箱与提交记录将被**公开留存**，
   并随本项目公开分发；
5. **本项目不因合并你的贡献而对你负有任何维护、支持或署名以外的义务。**
   贡献按「现状」提供，不附带任何明示或默示的担保。

若上述任一声明在你提交贡献之后变为不实，你应尽快通知维护者
（见 [SECURITY.md](SECURITY.md) 中的私密联系通道）。

---

## 六、如何表示接受

**目前采用 PR 内显式声明的方式**（本项目尚未接入自动化 CLA 机器人）。

在你的 Pull Request 描述中，按 [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)
的对应条目，逐字写下：

```
我已阅读并接受 CLA.md，包括其中第三节第 3 项（维护者可在闭源商业产品中使用我的贡献）。
署名：<你的 GitHub 用户名>
```

维护者会在合并前确认这一条。**没有这句话的 PR 不会被合并**，
无论代码质量如何——这不是对贡献者的不信任，而是这条链路一旦断了就很难事后补齐。

> 未来若接入 CLA Assistant 之类的 GitHub App，将以其记录为准，本节相应作废。

---

## 七、法人贡献

若你代表公司、组织或其他法人提交贡献，或你的贡献属于职务作品，
请**先通过 [SECURITY.md](SECURITY.md) 里的私密通道联系维护者**，
不要直接提 PR。法人贡献需要另行签署，且需由有权代表该法人的人签署。

---

## 八、其他

- 本协议不构成雇佣、合伙、代理或合资关系。
- 本协议的任一条款被认定无效或不可执行的，不影响其余条款的效力。
- 维护者可修订本协议。**修订不溯及既往**：你已提交的贡献适用你接受时的版本。
  本文件的历次修订可在本仓库的 git 历史中逐版比对。

---
---

# Contributor License Agreement (English translation)

> **The Chinese version above is authoritative.** This translation is provided
> for convenience; in case of any discrepancy, the Chinese version governs.

## 0. The thirty-second version

- You **keep** the copyright in your contribution. Nothing is assigned.
- You grant the maintainer a perpetual, irrevocable, **sublicensable** licence to use,
  modify and distribute your contribution **under any licence**, including a
  proprietary closed-source commercial one.
- Which means: **your code may end up in a paid closed-source product, and you will
  not be paid for it.**
- You confirm you wrote it, or that you have the right to submit it.
- The project itself remains GPL-3.0, and your contribution is published under
  GPL-3.0 along with it.

Declining these terms is a perfectly reasonable choice. You can still open issues,
report bugs, give documentation feedback, or fork and maintain your own version —
none of that requires signing this CLA.

## 1. Why a CLA and not a DCO

This project is developed by a single author who also ships a closed-source
commercial version; this repository is a functional subset of it, and the two share
one code base.

Under a DCO alone, any merged external contribution would be licensed to the project
under GPL-3.0 only, and the maintainer could **not** carry it into the closed-source
version. The code base would fork permanently the first time that happened.

The CLA states this up front rather than letting you discover after your PR is merged
that your code shipped in a commercial product. The cost to you is real and this
document does not attempt to minimise it.

## 2. Definitions

- **"the Project"** — CS2 Customizer, at <https://github.com/gufan0000/cs2-customizer>.
- **"the Maintainer"** — 孤帆 (gufan), copyright holder of the Project, and any
  successor designated in writing.
- **"You"** — the individual accepting this agreement. For legal entities, see §7.
- **"Contribution"** — any original work of authorship you intentionally submit to the
  Project, including source code, documentation, tests, criteria, configuration, assets
  and comments, submitted by pull request, issue, patch or any other means. It does
  **not** include material you conspicuously mark as "Not a Contribution".

## 3. Copyright licence

You **retain** all copyright in your Contribution.

You grant the Maintainer a perpetual, worldwide, non-exclusive, no-charge,
royalty-free, irrevocable licence to:

1. reproduce, modify, adapt, publicly display and publicly perform your Contribution;
2. distribute your Contribution and derivative works of it;
3. **sublicense the foregoing rights under any licence terms whatsoever** — including
   GPL-3.0, other open-source licences, and **proprietary closed-source commercial
   licences**.

Item 3 is the substance of this agreement and the only material difference from a DCO.
Please make sure you accept it.

**The Maintainer's obligation**: publicly released versions of the Project will be
released under GPL-3.0-or-later, and your Contribution will be available to everyone
under GPL-3.0-or-later as part of them. Nothing here restricts your own right to use,
publish or license your own Contribution however you wish.

## 4. Patent licence

You grant the Maintainer and all users of the Project a perpetual, worldwide,
non-exclusive, no-charge, royalty-free, irrevocable patent licence to make, have made,
use, offer to sell, sell, import and otherwise transfer your Contribution and works
incorporating it.

This licence covers only those patent claims you own or can license which are
necessarily infringed by your Contribution alone, or by the combination of your
Contribution with the version of the Project to which it was submitted.

**Defensive termination**: if any entity institutes patent litigation (including a
cross-claim or counterclaim) alleging that the Project, or a Contribution incorporated
in it, constitutes direct or contributory patent infringement, the patent licences
granted under this section to that entity terminate as of the date such litigation is
filed.

## 5. Your representations

You represent and warrant that:

1. each Contribution is your original creation, or you have obtained rights sufficient
   to make the grants above;
2. your Contribution contains no third-party code, assets or documentation that you are
   not entitled to license. Where third-party material is included, you have clearly
   identified its source and licence at each occurrence, and that licence is compatible
   with how the Project is distributed;
3. if you are employed, or party to any agreement that could affect ownership of your
   Contribution (employment contract, invention-assignment, non-compete, NDA and the
   like), you have obtained the necessary permission or a waiver;
4. you understand that your Contribution, together with your name, email address and
   commit records, will be **retained publicly** and distributed with the Project;
5. **merging your Contribution creates no obligation on the Project to maintain,
   support, or credit you beyond attribution in the commit history.** Contributions are
   provided "AS IS", without warranty of any kind, express or implied.

If any of the above ceases to be accurate after you submit, please notify the
Maintainer promptly via the private channel in [SECURITY.md](SECURITY.md).

## 6. How to indicate acceptance

The Project currently uses an **explicit statement inside the pull request**
(no automated CLA bot yet). In your PR description, per
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md), write:

```
I have read and accept CLA.md, including §3(3) (the maintainer may use my
contribution in a closed-source commercial product).
Signed: <your GitHub username>
```

The Maintainer will verify this before merging. **A PR without this statement will not
be merged**, regardless of code quality — not out of distrust, but because this chain
is very hard to repair after the fact.

> If a GitHub App such as CLA Assistant is adopted later, its records will govern and
> this section will be superseded.

## 7. Contributions by legal entities

If you are contributing on behalf of a company or other legal entity, or your
Contribution is a work made for hire, please **contact the Maintainer first** through
the private channel in [SECURITY.md](SECURITY.md) rather than opening a PR. Entity
contributions require a separate signature by someone authorised to bind the entity.

## 8. Miscellaneous

- This agreement creates no employment, partnership, agency or joint-venture
  relationship.
- If any provision is held invalid or unenforceable, the remainder stays in effect.
- The Maintainer may revise this agreement. **Revisions are not retroactive**: your
  already-submitted Contributions remain governed by the version you accepted. Every
  revision of this file is diffable in the repository's git history.
