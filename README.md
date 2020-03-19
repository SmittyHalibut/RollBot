# RollBot
A Slack dice rolling robot for Shadowrun and Fate style dice, using AWS API Gateway and Lambda.

# I AM NOT PROUD OF THIS CODE!!
This is literally a "learn how to use AWS APIGateway and Lambda" project that's survived and been used for years. I did NOT set out for this to be a shared, well supported tool.   I wrote it using Python 2.7 and haven't bothered to update it for 3.x.

# THIS IS NOT WELL DOCUMENTED!
I went through a "How to use API Gateway and Lambda to make a Slack Bot!" tutorial and set things up. I have no memory of what I did, or of the URL of the tutorial I used. If I get around to it, I might share the CloudFormation export of how things are configured now.

# THIS IS NOT SECURE!!
KMS costs $1/mo and I'm a cheap free-tier bastard.  So yes, the token needed to talk to Slack is in code.  No, that's not my token.  Put your own token there.

I mentioned I'm not proud of this code, right?

# RollBot!
With those disclaimers out of the way.  This is a Shadowrun style dice roller bot for Slack.  I also added Fate style dice support.

There are a couple other useful things in there, like a Food Fight style mess randomizer.  Also, inspired by the Corporate SINs Actual Play, I added support for what I call Pool Dice.  You as a player can add a die to your roll, but I as the GM get a die I can add to a roll later.  If you really need a bit more Umph, you can use it, but it gives me some Umph to use later.  

That's about all the time I have to document right now.  (I did mention it's not well documented, right?)

Shoot straight, conserve ammo, and NEVER make a deal with a dragon.
-Seventeen (aka SmittyHalibut in the 5th world.)
