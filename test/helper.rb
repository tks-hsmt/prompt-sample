require 'bundler/setup'
require 'test/unit'
require 'fluent/test'
require 'fluent/test/driver/filter'
require 'fluent/test/helpers'

# プラグインファイルを読み込む
plugin_dir = File.expand_path('../files/plugins', __dir__)
Dir.glob(File.join(plugin_dir, '*.rb')).sort.each { |f| require f }

class Test::Unit::TestCase
  include Fluent::Test::Helpers
end