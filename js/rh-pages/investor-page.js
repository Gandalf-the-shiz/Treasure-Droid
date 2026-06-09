import { renderInvestorUI } from '../ui/investor.js';

export async function renderInvestorPage(container) {
  container.innerHTML = '<div class="rh-inv-mount"></div>';
  const mount = container.querySelector('.rh-inv-mount');
  await renderInvestorUI(mount);
}
