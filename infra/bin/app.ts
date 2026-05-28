import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { GitlabStack } from '../lib/gitlab-stack';

const app = new cdk.App();

new GitlabStack(app, 'GitlabAiInceptionStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1',
  },
  instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.LARGE),
  sshCidr: '106.73.67.193/32',
  budgetAlertEmail: 'restofakito@gmail.com',
  startHourUtc: 9,   // 18:00 JST
  stopHourUtc: 15,   // 24:00 JST
  tags: {
    Project: 'gitlab-ai-inception',
    ManagedBy: 'cdk',
  },
});
