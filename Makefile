INSTANCE_ID := i-05639e1d48eadc145
REGION      := ap-northeast-1

.PHONY: start stop status ssh

start:
	aws ec2 start-instances --instance-ids $(INSTANCE_ID) --region $(REGION) --output text --query 'StartingInstances[0].CurrentState.Name'
	@echo "起動中... 約1分後にアクセス可能になります"
	@echo "GitLab: http://13.193.85.82"

stop:
	aws ec2 stop-instances --instance-ids $(INSTANCE_ID) --region $(REGION) --output text --query 'StoppingInstances[0].CurrentState.Name'
	@echo "停止中..."

status:
	@aws ec2 describe-instances --instance-ids $(INSTANCE_ID) --region $(REGION) \
		--query "Reservations[0].Instances[0].State.Name" --output text

ssh:
	ssh -i gitlab-ai.pem ubuntu@13.193.85.82
