import * as cdk from 'aws-cdk-lib';
import { GitlabStack } from '../lib/gitlab-stack';

const app = new cdk.App();

new GitlabStack(app, 'GitlabAiInceptionStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1',
  },
  sshCidr: '106.73.67.193/32',
  budgetAlertEmail: 'restofakito@gmail.com',
  startHourUtc: 0,   // 9:00 JST
  stopHourUtc: 13,   // 22:00 JST
  tags: {
    Project: 'gitlab-ai-inception',
    ManagedBy: 'cdk',
  },
});
